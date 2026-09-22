from datasette.app import Datasette
from markupsafe import Markup
from datasette_vite import ManifestError, vite_entry, vite_js_urls, vite_css_urls
from pathlib import Path
import json
import os
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
    # CSS links, then modulepreloads for imported chunks (depth-first), then the entry
    assert html.splitlines() == [
        '<link rel="stylesheet" href="/-/static-plugins/datasette_vite/gen/index-def456.css">',
        '<link rel="stylesheet" href="/-/static-plugins/datasette_vite/gen/shared-aaa111.css">',
        '<link rel="stylesheet" href="/-/static-plugins/datasette_vite/gen/deep-ccc333.css">',
        '<link rel="modulepreload" href="/-/static-plugins/datasette_vite/gen/shared-xyz789.js">',
        '<link rel="modulepreload" href="/-/static-plugins/datasette_vite/gen/deep-bbb222.js">',
        '<script type="module" src="/-/static-plugins/datasette_vite/gen/index-abc123.js"></script>',
    ]


@pytest.mark.asyncio
async def test_prod_mode_no_modulepreload_for_dynamic_imports(tmp_path):
    manifest = {
        "src/main.ts": {
            "file": "static/main-abc.js",
            "isEntry": True,
            "imports": ["_shared.js", "src/main.ts"],
            "dynamicImports": ["src/lazy.ts"],
        },
        "_shared.js": {"file": "static/shared.js"},
        "src/lazy.ts": {"file": "static/lazy.js", "isDynamicEntry": True},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    entry = vite_entry(
        datasette=Datasette(memory=True),
        plugin_package="datasette_vite",
        manifest_dir=tmp_path,
    )
    html = await entry("src/main.ts")
    assert html.splitlines() == [
        '<link rel="modulepreload" href="/-/static-plugins/datasette_vite/shared.js">',
        '<script type="module" src="/-/static-plugins/datasette_vite/main-abc.js"></script>',
    ]


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


# Dev config validation


def test_dev_paths_trailing_slash_added():
    datasette = _ds_with_vite_config(
        {"dev_paths": {"datasette_vite": "http://localhost:5179"}}
    )
    result = vite_js_urls(
        datasette=datasette,
        entrypoint="src/main.ts",
        plugin_package="datasette_vite",
    )
    assert result == [
        {"url": "http://localhost:5179/@vite/client", "module": True},
        {"url": "http://localhost:5179/src/main.ts", "module": True},
    ]


@pytest.mark.parametrize(
    "dev_path",
    ["javascript:alert(1)", "file:///etc/passwd", "localhost:5173/", "/relative/"],
)
def test_dev_paths_rejects_non_http(dev_path):
    datasette = _ds_with_vite_config({"dev_paths": {"datasette_vite": dev_path}})
    with pytest.raises(ValueError, match="must be an http\\(s\\) URL"):
        vite_js_urls(
            datasette=datasette,
            entrypoint="src/main.ts",
            plugin_package="datasette_vite",
        )


def test_dev_paths_allows_https():
    datasette = _ds_with_vite_config(
        {"dev_paths": {"datasette_vite": "https://dev.example.com:5173/x/"}}
    )
    result = vite_js_urls(
        datasette=datasette,
        entrypoint="src/main.ts",
        plugin_package="datasette_vite",
    )
    assert result[0] == {"url": "https://dev.example.com:5173/x/@vite/client", "module": True}


@pytest.mark.parametrize("port", [5180, "5180"])
def test_dev_ports_accepts_int_or_numeric_string(port):
    datasette = _ds_with_vite_config({"dev_ports": {"datasette_vite": port}})
    result = vite_js_urls(
        datasette=datasette,
        entrypoint="src/main.ts",
        plugin_package="datasette_vite",
    )
    assert result[0] == {"url": "http://localhost:5180/@vite/client", "module": True}


@pytest.mark.parametrize("port", ["abc", "5173/", '5173/"><script>', None])
def test_dev_ports_rejects_non_integer(port):
    datasette = _ds_with_vite_config({"dev_ports": {"datasette_vite": port}})
    with pytest.raises(ValueError, match="must be an integer"):
        vite_js_urls(
            datasette=datasette,
            entrypoint="src/main.ts",
            plugin_package="datasette_vite",
        )


@pytest.mark.parametrize("port", [0, 65536, -1])
def test_dev_ports_rejects_out_of_range(port):
    datasette = _ds_with_vite_config({"dev_ports": {"datasette_vite": port}})
    with pytest.raises(ValueError, match="out of range"):
        vite_js_urls(
            datasette=datasette,
            entrypoint="src/main.ts",
            plugin_package="datasette_vite",
        )


def test_vite_css_urls_dedupes_cycles_and_shared_css(tmp_path):
    manifest = {
        "src/main.ts": {
            "file": "static/main-abc.js",
            "isEntry": True,
            "css": ["static/main-abc.css", "static/shared-ddd.css"],
            "imports": ["_shared.js", "_other.js"],
        },
        "_shared.js": {
            "file": "static/shared.js",
            "css": ["static/shared-ddd.css", "static/only-shared.css"],
            "imports": ["src/main.ts"],
        },
        "_other.js": {
            "file": "static/other.js",
            "css": ["static/main-abc.css"],
        },
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    result = vite_css_urls(
        datasette=Datasette(memory=True),
        entrypoint="src/main.ts",
        plugin_package="datasette_vite",
        manifest_dir=tmp_path,
    )
    assert result == [
        "/-/static-plugins/datasette_vite/main-abc.css",
        "/-/static-plugins/datasette_vite/shared-ddd.css",
        "/-/static-plugins/datasette_vite/only-shared.css",
    ]


# Manifest caching


def test_manifest_parsed_once_per_mtime(tmp_path, monkeypatch):
    manifest = {"src/main.ts": {"file": "static/main-abc.js", "isEntry": True}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    calls = []
    real_loads = json.loads

    def counting_loads(*args, **kwargs):
        calls.append(1)
        return real_loads(*args, **kwargs)

    monkeypatch.setattr(json, "loads", counting_loads)
    datasette = Datasette(memory=True)
    for _ in range(2):
        vite_js_urls(
            datasette=datasette,
            entrypoint="src/main.ts",
            plugin_package="datasette_vite",
            manifest_dir=tmp_path,
        )
    assert len(calls) == 1


def test_rebuilt_manifest_is_picked_up(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({"src/main.ts": {"file": "static/main-old.js", "isEntry": True}})
    )
    os.utime(path, (1_000_000_000, 1_000_000_000))
    datasette = Datasette(memory=True)

    def js_url():
        return vite_js_urls(
            datasette=datasette,
            entrypoint="src/main.ts",
            plugin_package="datasette_vite",
            manifest_dir=tmp_path,
        )[0]["url"]

    assert js_url().endswith("/main-old.js")

    path.write_text(
        json.dumps({"src/main.ts": {"file": "static/main-new.js", "isEntry": True}})
    )
    os.utime(path, (1_000_000_100, 1_000_000_100))
    assert js_url().endswith("/main-new.js")


@pytest.mark.asyncio
async def test_vite_entry_reads_config_on_each_call(tmp_path):
    manifest = {"src/main.ts": {"file": "static/main-abc.js", "isEntry": True}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    datasette = Datasette(memory=True)
    entry = vite_entry(
        datasette=datasette,
        plugin_package="datasette_vite",
        manifest_dir=tmp_path,
    )
    html = await entry("src/main.ts")
    assert 'src="/-/static-plugins/datasette_vite/main-abc.js"' in html

    # On Datasette 1.0a, plugin_config() reads from datasette.config
    datasette.config = {
        "plugins": {"datasette-vite": {"dev_ports": {"datasette_vite": 5181}}}
    }
    html = await entry("src/main.ts")
    assert '<script type="module" src="http://localhost:5181/@vite/client"></script>' in html
    assert "main-abc.js" not in html


# Startup warning


@pytest.mark.asyncio
async def test_startup_warns_in_dev_mode(caplog):
    datasette = _ds_with_vite_config(
        {
            "dev_ports": {"datasette_vite": 5180},
            "dev_paths": {"datasette_other": "http://localhost:5179/"},
        }
    )
    await datasette.invoke_startup()
    records = [r for r in caplog.records if "dev mode is ON" in r.getMessage()]
    assert len(records) == 1
    assert records[0].levelname == "WARNING"
    assert "datasette_other, datasette_vite" in records[0].getMessage()


@pytest.mark.asyncio
async def test_startup_silent_without_dev_config(caplog):
    datasette = Datasette(memory=True)
    await datasette.invoke_startup()
    assert "dev mode is ON" not in caplog.text


# Jinja global


def _page_template(tmp_path, body):
    pages = tmp_path / "templates" / "pages"
    pages.mkdir(parents=True)
    (pages / "vite-test.html").write_text(body)
    return str(tmp_path / "templates")


@pytest.mark.asyncio
async def test_jinja_global_renders_entry(tmp_path):
    manifest = {
        "src/pages/index.ts": {
            "file": "static/gen/index-abc123.js",
            "isEntry": True,
            "css": ["static/gen/index-def456.css"],
        }
    }
    manifest_dir = tmp_path / "manifest"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.json").write_text(json.dumps(manifest))
    template_dir = _page_template(
        tmp_path,
        '{{ vite_entry("datasette_vite", "src/pages/index.ts", "%s") }}' % manifest_dir,
    )
    datasette = Datasette(memory=True, template_dir=template_dir)
    response = await datasette.client.get("/vite-test")
    assert response.status_code == 200
    assert (
        '<link rel="stylesheet" href="/-/static-plugins/datasette_vite/gen/index-def456.css">'
        in response.text
    )
    assert (
        '<script type="module" src="/-/static-plugins/datasette_vite/gen/index-abc123.js"></script>'
        in response.text
    )
    assert "&lt;" not in response.text


@pytest.mark.asyncio
async def test_jinja_global_dev_mode(tmp_path):
    template_dir = _page_template(
        tmp_path, '{{ vite_entry("datasette_vite", "src/main.ts") }}'
    )
    datasette = Datasette(
        memory=True,
        template_dir=template_dir,
        metadata={"plugins": {"datasette-vite": {"dev_ports": {"datasette_vite": 5182}}}},
    )
    response = await datasette.client.get("/vite-test")
    assert response.status_code == 200
    assert (
        '<script type="module" src="http://localhost:5182/src/main.ts"></script>'
        in response.text
    )


# nonce / crossorigin


def _split_manifest(tmp_path):
    manifest = {
        "src/main.ts": {
            "file": "static/main-abc.js",
            "isEntry": True,
            "css": ["static/main-abc.css"],
            "imports": ["_shared.js"],
        },
        "_shared.js": {"file": "static/shared.js", "css": ["static/shared.css"]},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))


@pytest.mark.asyncio
async def test_nonce_and_crossorigin_on_every_prod_tag(tmp_path):
    _split_manifest(tmp_path)
    entry = vite_entry(
        datasette=Datasette(memory=True),
        plugin_package="datasette_vite",
        manifest_dir=tmp_path,
        nonce="abc",
        crossorigin="anonymous",
    )
    html = await entry("src/main.ts")
    assert html.splitlines() == [
        '<link rel="stylesheet" href="/-/static-plugins/datasette_vite/main-abc.css" nonce="abc" crossorigin="anonymous">',
        '<link rel="stylesheet" href="/-/static-plugins/datasette_vite/shared.css" nonce="abc" crossorigin="anonymous">',
        '<link rel="modulepreload" href="/-/static-plugins/datasette_vite/shared.js" nonce="abc" crossorigin="anonymous">',
        '<script type="module" src="/-/static-plugins/datasette_vite/main-abc.js" nonce="abc" crossorigin="anonymous"></script>',
    ]


@pytest.mark.asyncio
async def test_nonce_and_crossorigin_in_dev_mode():
    datasette = _ds_with_vite_config({"dev_ports": {"datasette_vite": 5180}})
    entry = vite_entry(
        datasette=datasette,
        plugin_package="datasette_vite",
        nonce="abc",
        crossorigin="",
    )
    html = await entry("src/main.ts")
    assert html == (
        '<script type="module" src="http://localhost:5180/@vite/client" nonce="abc" crossorigin></script>\n'
        '<script type="module" src="http://localhost:5180/src/main.ts" nonce="abc" crossorigin></script>'
    )


@pytest.mark.asyncio
async def test_nonce_and_crossorigin_are_escaped(tmp_path):
    _split_manifest(tmp_path)
    entry = vite_entry(
        datasette=Datasette(memory=True),
        plugin_package="datasette_vite",
        manifest_dir=tmp_path,
        nonce='"><script>',
        crossorigin='use-credentials"',
    )
    html = await entry("src/main.ts")
    assert "<script>" not in html
    assert 'nonce="&#34;&gt;&lt;script&gt;"' in html
    assert 'crossorigin="use-credentials&#34;"' in html


@pytest.mark.asyncio
async def test_no_nonce_or_crossorigin_by_default(tmp_path):
    _split_manifest(tmp_path)
    entry = vite_entry(
        datasette=Datasette(memory=True),
        plugin_package="datasette_vite",
        manifest_dir=tmp_path,
    )
    html = await entry("src/main.ts")
    assert "nonce" not in html
    assert "crossorigin" not in html


@pytest.mark.asyncio
async def test_jinja_global_accepts_nonce(tmp_path):
    template_dir = _page_template(
        tmp_path,
        '{{ vite_entry("datasette_vite", "src/main.ts", nonce="n1", crossorigin="anonymous") }}',
    )
    datasette = Datasette(
        memory=True,
        template_dir=template_dir,
        metadata={"plugins": {"datasette-vite": {"dev_ports": {"datasette_vite": 5182}}}},
    )
    response = await datasette.client.get("/vite-test")
    assert (
        '<script type="module" src="http://localhost:5182/src/main.ts" nonce="n1" crossorigin="anonymous"></script>'
        in response.text
    )
