from datasette.app import Datasette
from datasette_vite import vite_entry
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
async def test_dev_mode():
    datasette = Datasette(memory=True)
    entry = vite_entry(
        datasette=datasette,
        plugin_package="datasette_vite",
        vite_dev_path="http://localhost:5178/",
    )
    html = await entry("src/pages/index.ts")
    assert '<script type="module" src="http://localhost:5178/@vite/client"></script>' in html
    assert '<script type="module" src="http://localhost:5178/src/pages/index.ts"></script>' in html


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
    entry = vite_entry(
        datasette=datasette,
        plugin_package="datasette_vite",
        manifest_dir=tmp_path,
    )
    with pytest.raises(ValueError, match="not found in manifest"):
        await entry("src/pages/index.ts")
