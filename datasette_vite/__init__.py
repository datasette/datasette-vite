from datasette import hookimpl
from pathlib import Path
from pydantic import BaseModel
from textwrap import dedent
from typing import Awaitable, Callable, Optional
import importlib
import json

__all__ = [
    "ManifestChunk",
    "ManifestError",
    "vite_css_urls",
    "vite_entry",
    "vite_js_urls",
]

STATIC_PREFIX = "static"


class ManifestError(ValueError):
    """Raised when a Vite manifest is missing, malformed, or references an unexpected path."""


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


def _resolve_vite_dev_path(datasette, plugin_package: str) -> str | None:
    config = datasette.plugin_config("datasette-vite") or {}
    dev_paths = config.get("dev_paths") or {}
    if plugin_package in dev_paths:
        return dev_paths[plugin_package]
    dev_ports = config.get("dev_ports") or {}
    if plugin_package in dev_ports:
        return f"http://localhost:{dev_ports[plugin_package]}/"
    return None


def _manifest_path(plugin_package: str, manifest_dir: str | Path | None) -> Path:
    if manifest_dir is not None:
        return Path(manifest_dir) / "manifest.json"
    mod = importlib.import_module(plugin_package)
    mod_file = getattr(mod, "__file__", None)
    if mod_file is None:
        raise ManifestError(
            f"{plugin_package} has no __file__ (namespace package?); "
            "pass manifest_dir= explicitly"
        )
    return Path(mod_file).parent / "manifest.json"


def _load_manifest(
    plugin_package: str,
    manifest_dir: str | Path | None = None,
) -> dict[str, ManifestChunk]:
    path = _manifest_path(plugin_package, manifest_dir)
    if not path.exists():
        raise ManifestError(
            f"Vite manifest not found at {path}. Run `vite build` and copy "
            f"manifest.json into the {plugin_package} package (or pass manifest_dir=)."
        )
    raw = json.loads(path.read_text())
    return {k: ManifestChunk(**v) for k, v in raw.items()}


def _static_url(datasette, plugin_package: str, built_path: str) -> str:
    p = Path(built_path)
    if ".." in p.parts or p.is_absolute():
        raise ManifestError(
            f"Refusing manifest path {built_path!r}: contains '..' or is absolute"
        )
    if p.parts[:1] != (STATIC_PREFIX,):
        raise ManifestError(
            f"Manifest path {built_path!r} does not start with '{STATIC_PREFIX}/'. "
            f"Set rollupOptions.output.*FileNames to '{STATIC_PREFIX}/[name]-[hash]...' "
            "(see README)."
        )
    return datasette.urls.static_plugins(
        plugin_package, p.relative_to(STATIC_PREFIX).as_posix()
    )


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
        urls.append(_static_url(datasette, plugin_package, css))

    seen = set()

    def collect_import_css(chunk_key):
        if chunk_key in seen:
            return
        seen.add(chunk_key)
        imp_chunk = manifest.get(chunk_key)
        if not imp_chunk:
            return
        for css in imp_chunk.css or []:
            urls.append(_static_url(datasette, plugin_package, css))
        for sub_import in imp_chunk.imports or []:
            collect_import_css(sub_import)

    for imp in chunk.imports or []:
        collect_import_css(imp)

    return urls


def vite_js_urls(
    datasette,
    entrypoint: str,
    plugin_package: str,
    manifest_dir: str | Path | None = None,
) -> list:
    vite_dev_path = _resolve_vite_dev_path(datasette, plugin_package)
    if vite_dev_path:
        return [
            {"url": f"{vite_dev_path}@vite/client", "module": True},
            {"url": f"{vite_dev_path}{entrypoint}", "module": True},
        ]
    manifest = _load_manifest(plugin_package, manifest_dir)
    chunk = manifest.get(entrypoint)
    if not chunk:
        raise ValueError(f"Entrypoint {entrypoint} not found in manifest")
    src = _static_url(datasette, plugin_package, chunk.file)
    return [{"url": src, "module": True}]


def vite_css_urls(
    datasette,
    entrypoint: str,
    plugin_package: str,
    manifest_dir: str | Path | None = None,
) -> list[str]:
    vite_dev_path = _resolve_vite_dev_path(datasette, plugin_package)
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
    manifest_dir: str | Path | None = None,
) -> Callable[[str], Awaitable[str]]:
    vite_dev_path = _resolve_vite_dev_path(datasette, plugin_package)
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

        src = _static_url(datasette, plugin_package, chunk.file)
        parts.append(f'<script type="module" src="{src}"></script>')

        return "\n".join(parts)

    return entry
