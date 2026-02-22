import re
import pytest
from pathlib import Path
from datasette.app import Datasette
from datasette_vite import vite_entry

FIXTURE_DIR = Path(__file__).parent / "vite-fixtures"

FIXTURES = [
    ("vanilla-ts", "src/main.ts"),
    ("svelte-ts", "src/main.ts"),
    ("react-ts", "src/main.tsx"),
]


def _manifest_path(fixture_name):
    return FIXTURE_DIR / fixture_name / "dist" / ".vite" / "manifest.json"


def _skip_unless_built(fixture_name):
    if not _manifest_path(fixture_name).exists():
        pytest.skip(f"{fixture_name} not built (run `just build-fixtures`)")


@pytest.mark.parametrize("fixture_name,entrypoint", FIXTURES)
@pytest.mark.asyncio
async def test_real_manifest_html(fixture_name, entrypoint):
    """vite_entry() generates valid HTML with correct asset references from real Vite builds."""
    _skip_unless_built(fixture_name)

    datasette = Datasette(memory=True)
    entry = vite_entry(
        datasette=datasette,
        plugin_package="datasette_vite",
        manifest_dir=_manifest_path(fixture_name).parent,
    )
    html = await entry(entrypoint)

    assert '<script type="module" src="' in html

    dist_dir = FIXTURE_DIR / fixture_name / "dist"
    for src in re.findall(r'src="/-/static-plugins/datasette_vite/([^"]+)"', html):
        assert (dist_dir / "static" / src).exists(), f"JS file missing: {src}"
    for href in re.findall(r'href="/-/static-plugins/datasette_vite/([^"]+)"', html):
        assert (dist_dir / "static" / href).exists(), f"CSS file missing: {href}"


@pytest.mark.parametrize(
    "fixture_name,entrypoint",
    [
        ("svelte-ts", "src/main.ts"),
        ("react-ts", "src/main.tsx"),
    ],
)
@pytest.mark.asyncio
async def test_framework_fixtures_have_css(fixture_name, entrypoint):
    """Svelte and React fixtures produce CSS link tags."""
    _skip_unless_built(fixture_name)

    datasette = Datasette(memory=True)
    entry = vite_entry(
        datasette=datasette,
        plugin_package="datasette_vite",
        manifest_dir=_manifest_path(fixture_name).parent,
    )
    html = await entry(entrypoint)
    assert '<link rel="stylesheet"' in html
