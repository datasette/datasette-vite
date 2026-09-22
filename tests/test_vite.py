from datasette.app import Datasette
from markupsafe import Markup
from datasette_vite import ManifestError, vite_entry, vite_js_urls, vite_css_urls
from pathlib import Path
import json
import pytest


@pytest.mark.asyncio
async def test_plugin_is_installed():
    datasette = Datasette(memory=True)
    response = await datasette.client.get("/-/plugins.json")
    assert response.status_code == 200
    installed_plugins = {p["name"] for p in response.json()}
    assert "datasette-vite" in installed_plugins


@pytest.mark.asyncio
async def test_prod_mode(tmp_path):
    manifest = {
        "src/pages/index.ts": {
            "file": "static/gen/index-abc123.js",
            "src": "src/pages/index.ts",
            "isEntry": True,
            "css": ["static/gen/index-def456.css"],
        }
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    datasette = Datasette(memory=True)
    entry = vite_entry(
        datasette=datasette,
        plugin_package="datasette_vite",
        manifest_dir=tmp_path,
    )
    html = await entry("src/pages/index.ts")
    assert '<link rel="stylesheet" href="/-/static-plugins/datasette_vite/gen/index-def456.css">' in html
    assert '<script type="module" src="/-/static-plugins/datasette_vite/gen/index-abc123.js"></script>' in html


@pytest.mark.asyncio
async def test_prod_mode_no_css(tmp_path):
    manifest = {
        "src/pages/index.ts": {
            "file": "static/gen/index-abc123.js",
            "src": "src/pages/index.ts",
            "isEntry": True,
        }
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    datasette = Datasette(memory=True)
    entry = vite_entry(
        datasette=datasette,
        plugin_package="datasette_vite",
        manifest_dir=tmp_path,
    )
    html = await entry("src/pages/index.ts")
    assert "<link" not in html
    assert '<script type="module" src="/-/static-plugins/datasette_vite/gen/index-abc123.js"></script>' in html


@pytest.mark.asyncio
async def test_prod_mode_imported_chunk_css(tmp_path):
    manifest = {
        "src/pages/index.ts": {
            "file": "static/gen/index-abc123.js",
            "src": "src/pages/index.ts",
            "isEntry": True,
            "css": ["static/gen/index-def456.css"],
            "imports": ["_shared-xyz789.js"],
        },
        "_shared-xyz789.js": {
            "file": "static/gen/shared-xyz789.js",
            "css": ["static/gen/shared-aaa111.css"],
            "imports": ["_deep-bbb222.js"],
        },
        "_deep-bbb222.js": {
            "file": "static/gen/deep-bbb222.js",
            "css": ["static/gen/deep-ccc333.css"],
        },
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    datasette = Datasette(memory=True)
    entry = vite_entry(
        datasette=datasette,
        plugin_package="datasette_vite",
        manifest_dir=tmp_path,
    )
    html = await entry("src/pages/index.ts")
    # Direct CSS from entry chunk
    assert '<link rel="stylesheet" href="/-/static-plugins/datasette_vite/gen/index-def456.css">' in html
    # CSS from first-level imported chunk
    assert '<link rel="stylesheet" href="/-/static-plugins/datasette_vite/gen/shared-aaa111.css">' in html
    # CSS from recursively imported chunk
    assert '<link rel="stylesheet" href="/-/static-plugins/datasette_vite/gen/deep-ccc333.css">' in html
    # The JS entry script
    assert '<script type="module" src="/-/static-plugins/datasette_vite/gen/index-abc123.js"></script>' in html


@pytest.mark.asyncio
async def test_missing_entrypoint(tmp_path):
    (tmp_path / "manifest.json").write_text("{}")

    datasette = Datasette(memory=True)
    entry = vite_entry(
        datasette=datasette,
        plugin_package="datasette_vite",
        manifest_dir=tmp_path,
    )
    with pytest.raises(ValueError, match="not found in manifest"):
        await entry("src/pages/missing.ts")


@pytest.mark.asyncio
async def test_missing_manifest(tmp_path):
    datasette = Datasette(memory=True)
    with pytest.raises(ManifestError, match="manifest not found") as excinfo:
        entry = vite_entry(
            datasette=datasette,
            plugin_package="datasette_vite",
            manifest_dir=tmp_path,
        )
        await entry("src/pages/index.ts")
    assert str(tmp_path / "manifest.json") in str(excinfo.value)


def test_manifest_error_is_value_error():
    assert issubclass(ManifestError, ValueError)


def test_manifest_path_outside_static(tmp_path):
    manifest = {"src/main.ts": {"file": "assets/x.js", "isEntry": True}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ManifestError, match="does not start with 'static/'"):
        vite_js_urls(
            datasette=Datasette(memory=True),
            entrypoint="src/main.ts",
            plugin_package="datasette_vite",
            manifest_dir=tmp_path,
        )


def test_manifest_path_with_dotdot(tmp_path):
    manifest = {"src/main.ts": {"file": "static/../x.js", "isEntry": True}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ManifestError, match="contains '..'"):
        vite_js_urls(
            datasette=Datasette(memory=True),
            entrypoint="src/main.ts",
            plugin_package="datasette_vite",
            manifest_dir=tmp_path,
        )


def test_dotted_plugin_package_resolves_leaf_directory(tmp_path, monkeypatch):
    sub = tmp_path / "vite_dotted_pkg" / "sub"
    sub.mkdir(parents=True)
    (tmp_path / "vite_dotted_pkg" / "__init__.py").write_text("")
    (sub / "__init__.py").write_text("")
    manifest = {"src/main.ts": {"file": "static/main-abc.js", "isEntry": True}}
    (sub / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.syspath_prepend(str(tmp_path))

    result = vite_js_urls(
        datasette=Datasette(memory=True),
        entrypoint="src/main.ts",
        plugin_package="vite_dotted_pkg.sub",
    )
    assert result == [
        {"url": "/-/static-plugins/vite_dotted_pkg.sub/main-abc.js", "module": True},
    ]


# vite_js_urls / vite_css_urls tests


def test_vite_js_urls_prod_mode(tmp_path):
    manifest = {
        "src/sidebar/index.ts": {
            "file": "static/gen/index-abc123.js",
            "src": "src/sidebar/index.ts",
            "isEntry": True,
            "css": ["static/gen/index-def456.css"],
        }
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    datasette = Datasette(memory=True)
    result = vite_js_urls(
        datasette=datasette,
        entrypoint="src/sidebar/index.ts",
        plugin_package="datasette_vite",
        manifest_dir=tmp_path,
    )
    assert result == [
        {"url": "/-/static-plugins/datasette_vite/gen/index-abc123.js", "module": True},
    ]


def test_vite_css_urls_prod_mode(tmp_path):
    manifest = {
        "src/sidebar/index.ts": {
            "file": "static/gen/index-abc123.js",
            "src": "src/sidebar/index.ts",
            "isEntry": True,
            "css": ["static/gen/index-def456.css"],
            "imports": ["_shared-xyz789.js"],
        },
        "_shared-xyz789.js": {
            "file": "static/gen/shared-xyz789.js",
            "css": ["static/gen/shared-aaa111.css"],
            "imports": ["_deep-bbb222.js"],
        },
        "_deep-bbb222.js": {
            "file": "static/gen/deep-bbb222.js",
            "css": ["static/gen/deep-ccc333.css"],
        },
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    datasette = Datasette(memory=True)
    result = vite_css_urls(
        datasette=datasette,
        entrypoint="src/sidebar/index.ts",
        plugin_package="datasette_vite",
        manifest_dir=tmp_path,
    )
    assert result == [
        "/-/static-plugins/datasette_vite/gen/index-def456.css",
        "/-/static-plugins/datasette_vite/gen/shared-aaa111.css",
        "/-/static-plugins/datasette_vite/gen/deep-ccc333.css",
    ]


def test_vite_js_urls_missing_entrypoint(tmp_path):
    (tmp_path / "manifest.json").write_text("{}")

    datasette = Datasette(memory=True)
    with pytest.raises(ValueError, match="not found in manifest"):
        vite_js_urls(
            datasette=datasette,
            entrypoint="src/missing.ts",
            plugin_package="datasette_vite",
            manifest_dir=tmp_path,
        )


def test_vite_css_urls_missing_entrypoint(tmp_path):
    (tmp_path / "manifest.json").write_text("{}")

    datasette = Datasette(memory=True)
    with pytest.raises(ValueError, match="not found in manifest"):
        vite_css_urls(
            datasette=datasette,
            entrypoint="src/missing.ts",
            plugin_package="datasette_vite",
            manifest_dir=tmp_path,
        )


# Plugin-config resolution of dev path


def _ds_with_vite_config(config):
    return Datasette(memory=True, metadata={"plugins": {"datasette-vite": config}})


@pytest.mark.asyncio
async def test_vite_entry_dev_path_from_plugin_config():
    datasette = _ds_with_vite_config(
        {"dev_paths": {"datasette_vite": "http://localhost:5179/"}}
    )
    entry = vite_entry(datasette=datasette, plugin_package="datasette_vite")
    html = await entry("src/pages/index.ts")
    assert '<script type="module" src="http://localhost:5179/@vite/client"></script>' in html
    assert '<script type="module" src="http://localhost:5179/src/pages/index.ts"></script>' in html


@pytest.mark.asyncio
async def test_vite_entry_dev_port_from_plugin_config():
    datasette = _ds_with_vite_config({"dev_ports": {"datasette_vite": 5180}})
    entry = vite_entry(datasette=datasette, plugin_package="datasette_vite")
    html = await entry("src/pages/index.ts")
    assert '<script type="module" src="http://localhost:5180/@vite/client"></script>' in html
    assert '<script type="module" src="http://localhost:5180/src/pages/index.ts"></script>' in html


@pytest.mark.asyncio
async def test_plugin_config_only_for_matching_package(tmp_path):
    manifest = {
        "src/pages/index.ts": {
            "file": "static/gen/index-abc123.js",
            "src": "src/pages/index.ts",
            "isEntry": True,
        }
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    datasette = _ds_with_vite_config(
        {"dev_paths": {"some_other_plugin": "http://localhost:5179/"}}
    )
    entry = vite_entry(
        datasette=datasette,
        plugin_package="datasette_vite",
        manifest_dir=tmp_path,
    )
    html = await entry("src/pages/index.ts")
    # Falls through to manifest because the dev_paths entry is for a different package
    assert '<script type="module" src="/-/static-plugins/datasette_vite/gen/index-abc123.js"></script>' in html
    assert "5179" not in html


def test_vite_js_urls_dev_path_from_plugin_config():
    datasette = _ds_with_vite_config(
        {"dev_paths": {"datasette_vite": "http://localhost:5179/"}}
    )
    result = vite_js_urls(
        datasette=datasette,
        entrypoint="src/sidebar/index.ts",
        plugin_package="datasette_vite",
    )
    assert result == [
        {"url": "http://localhost:5179/@vite/client", "module": True},
        {"url": "http://localhost:5179/src/sidebar/index.ts", "module": True},
    ]


def test_vite_js_urls_dev_port_from_plugin_config():
    datasette = _ds_with_vite_config({"dev_ports": {"datasette_vite": 5180}})
    result = vite_js_urls(
        datasette=datasette,
        entrypoint="src/sidebar/index.ts",
        plugin_package="datasette_vite",
    )
    assert result == [
        {"url": "http://localhost:5180/@vite/client", "module": True},
        {"url": "http://localhost:5180/src/sidebar/index.ts", "module": True},
    ]


def test_vite_css_urls_dev_path_from_plugin_config():
    datasette = _ds_with_vite_config(
        {"dev_paths": {"datasette_vite": "http://localhost:5179/"}}
    )
    result = vite_css_urls(
        datasette=datasette,
        entrypoint="src/sidebar/index.ts",
        plugin_package="datasette_vite",
    )
    assert result == []


def test_dev_paths_takes_precedence_over_dev_ports():
    datasette = _ds_with_vite_config(
        {
            "dev_paths": {"datasette_vite": "http://localhost:5179/-/x/"},
            "dev_ports": {"datasette_vite": 5180},
        }
    )
    result = vite_js_urls(
        datasette=datasette,
        entrypoint="src/sidebar/index.ts",
        plugin_package="datasette_vite",
    )
    assert result == [
        {"url": "http://localhost:5179/-/x/@vite/client", "module": True},
        {"url": "http://localhost:5179/-/x/src/sidebar/index.ts", "module": True},
    ]


# HTML escaping


@pytest.mark.asyncio
async def test_prod_mode_escapes_manifest_values(tmp_path):
    manifest = {
        "src/main.ts": {
            "file": 'static/x".js',
            "isEntry": True,
            "css": ['static/y"><script>alert(1)</script>.css'],
        }
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    entry = vite_entry(
        datasette=Datasette(memory=True),
        plugin_package="datasette_vite",
        manifest_dir=tmp_path,
    )
    html = await entry("src/main.ts")
    assert isinstance(html, Markup)
    assert 'src="/-/static-plugins/datasette_vite/x&#34;.js"' in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    # Only the attribute delimiters remain as raw quotes
    assert html.count('"') == 8


@pytest.mark.asyncio
async def test_dev_mode_escapes_dev_path_and_entrypoint():
    datasette = _ds_with_vite_config(
        {"dev_paths": {"datasette_vite": 'http://localhost:5179/"x/'}}
    )
    entry = vite_entry(datasette=datasette, plugin_package="datasette_vite")
    html = await entry('src/"main.ts')
    assert isinstance(html, Markup)
    assert (
        html
        == '<script type="module" src="http://localhost:5179/&#34;x/@vite/client"></script>\n'
        '<script type="module" src="http://localhost:5179/&#34;x/src/&#34;main.ts"></script>'
    )


@pytest.mark.asyncio
async def test_prod_mode_returns_markup(tmp_path):
    manifest = {"src/main.ts": {"file": "static/main-abc.js", "isEntry": True}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    entry = vite_entry(
        datasette=Datasette(memory=True),
        plugin_package="datasette_vite",
        manifest_dir=tmp_path,
    )
    html = await entry("src/main.ts")
    assert isinstance(html, Markup)
    # Markup is not double-escaped when interpolated into other Markup
    assert str(Markup("{}").format(html)) == str(html)
