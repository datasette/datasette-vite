from datasette import hookimpl
from pathlib import Path
from pydantic import BaseModel
from textwrap import dedent
from typing import Awaitable, Callable, Optional
import json


class ManifestChunk(BaseModel):
    """Vite manifest chunk."""

    src: Optional[str] = None
    file: str
    css: Optional[list[str]] = None
    assets: Optional[list[str]] = None
    isEntry: Optional[bool] = None
    name: Optional[str] = None
    isDynamicEntry: Optional[bool] = None
    imports: Optional[list[str]] = None
    dynamicImports: Optional[list[str]] = None


def _load_manifest(
    plugin_package: str,
    manifest_dir: str | Path | None = None,
) -> dict[str, ManifestChunk]:
    if manifest_dir is None:
        mod = __import__(plugin_package)
        mod_file = mod.__file__
        assert mod_file is not None, f"Module {plugin_package} has no __file__"
        resolved_dir = Path(mod_file).parent
    else:
        resolved_dir = Path(manifest_dir)
    manifest_path = resolved_dir / "manifest.json"
    if manifest_path.exists():
        manifest_raw = json.loads(manifest_path.read_text())
        return {k: ManifestChunk(**v) for k, v in manifest_raw.items()}
    return {}


def _collect_css_urls(
    datasette,
    plugin_package: str,
    manifest: dict[str, ManifestChunk],
    entrypoint: str,
) -> list[str]:
    chunk = manifest.get(entrypoint)
    if not chunk:
        return []
    urls = []
    for css in chunk.css or []:
        file = str(Path(css).relative_to("static"))
        urls.append(datasette.urls.static_plugins(plugin_package, file))

    seen = set()

    def collect_import_css(chunk_key):
        if chunk_key in seen:
            return
        seen.add(chunk_key)
        imp_chunk = manifest.get(chunk_key)
        if not imp_chunk:
            return
        for css in imp_chunk.css or []:
            file = str(Path(css).relative_to("static"))
            urls.append(datasette.urls.static_plugins(plugin_package, file))
        for sub_import in imp_chunk.imports or []:
            collect_import_css(sub_import)

    for imp in chunk.imports or []:
        collect_import_css(imp)

    return urls


def vite_js_urls(
    datasette,
    entrypoint: str,
    plugin_package: str,
    vite_dev_path: str | None = None,
    manifest_dir: str | Path | None = None,
) -> list:
    if vite_dev_path:
        return [
            {"url": f"{vite_dev_path}@vite/client", "module": True},
            {"url": f"{vite_dev_path}{entrypoint}", "module": True},
        ]
    manifest = _load_manifest(plugin_package, manifest_dir)
    chunk = manifest.get(entrypoint)
    if not chunk:
        raise ValueError(f"Entrypoint {entrypoint} not found in manifest")
    file = str(Path(chunk.file).relative_to("static"))
    src = datasette.urls.static_plugins(plugin_package, file)
    return [{"url": src, "module": True}]


def vite_css_urls(
    datasette,
    entrypoint: str,
    plugin_package: str,
    vite_dev_path: str | None = None,
    manifest_dir: str | Path | None = None,
) -> list[str]:
    if vite_dev_path:
        return []
    manifest = _load_manifest(plugin_package, manifest_dir)
    chunk = manifest.get(entrypoint)
    if not chunk:
        raise ValueError(f"Entrypoint {entrypoint} not found in manifest")
    return _collect_css_urls(datasette, plugin_package, manifest, entrypoint)


def vite_entry(
    datasette,
    plugin_package: str,
    vite_dev_path: str | None = None,
    manifest_dir: str | Path | None = None,
) -> Callable[[str], Awaitable[str]]:
    manifest: dict[str, ManifestChunk] = {}
    if not vite_dev_path:
        manifest = _load_manifest(plugin_package, manifest_dir)

    async def entry(entrypoint: str) -> str:
        if vite_dev_path:
            return dedent(f"""

          <script type="module" src="{vite_dev_path}@vite/client"></script>
          <script type="module" src="{vite_dev_path}{entrypoint}"></script>

          """)

        chunk = manifest.get(entrypoint)
        if not chunk:
            raise ValueError(f"Entrypoint {entrypoint} not found in manifest")
        parts = []

        css_urls = _collect_css_urls(datasette, plugin_package, manifest, entrypoint)
        for href in css_urls:
            parts.append(f'<link rel="stylesheet" href="{href}">')

        file = str(Path(chunk.file).relative_to("static"))
        src = datasette.urls.static_plugins(plugin_package, file)
        parts.append(f'<script type="module" src="{src}"></script>')

        return "\n".join(parts)

    return entry
