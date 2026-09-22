from datasette import hookimpl
from markupsafe import Markup, escape
from pathlib import Path
from pydantic import BaseModel
from typing import Awaitable, Callable, Optional
from urllib.parse import urlsplit
import importlib
import json
import logging

__all__ = [
    "ManifestChunk",
    "ManifestError",
    "vite_css_urls",
    "vite_entry",
    "vite_js_urls",
]

STATIC_PREFIX = "static"

logger = logging.getLogger("datasette_vite")


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
        raw = str(dev_paths[plugin_package])
        parts = urlsplit(raw)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(
                f"datasette-vite dev_paths.{plugin_package} must be an http(s) URL, "
                f"got {raw!r}"
            )
        return raw if raw.endswith("/") else raw + "/"
    dev_ports = config.get("dev_ports") or {}
    if plugin_package in dev_ports:
        raw_port = dev_ports[plugin_package]
        try:
            port = int(raw_port)
        except (TypeError, ValueError):
            raise ValueError(
                f"datasette-vite dev_ports.{plugin_package} must be an integer, "
                f"got {raw_port!r}"
            ) from None
        if not 1 <= port <= 65535:
            raise ValueError(
                f"datasette-vite dev_ports.{plugin_package} out of range: {port}"
            )
        return f"http://localhost:{port}/"
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


# Parsed manifests keyed on resolved path; the mtime lets a rebuilt manifest be
# picked up without restarting Datasette.
_MANIFEST_CACHE: dict[Path, tuple[float, dict[str, ManifestChunk]]] = {}


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
    mtime = path.stat().st_mtime
    cached = _MANIFEST_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    raw = json.loads(path.read_text())
    manifest = {k: ManifestChunk(**v) for k, v in raw.items()}
    _MANIFEST_CACHE[path] = (mtime, manifest)
    return manifest


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
    urls: list[str] = []
    seen_chunks: set[str] = set()
    seen_urls: set[str] = set()

    def visit(chunk_key: str) -> None:
        if chunk_key in seen_chunks:
            return
        seen_chunks.add(chunk_key)
        chunk = manifest.get(chunk_key)
        if not chunk:
            return
        for css in chunk.css or []:
            url = _static_url(datasette, plugin_package, css)
            if url not in seen_urls:
                seen_urls.add(url)
                urls.append(url)
        for imp in chunk.imports or []:
            visit(imp)

    visit(entrypoint)
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
) -> Callable[[str], Awaitable[Markup]]:
    # Config and manifest are resolved on every call (the manifest is cached), so
    # the returned callable can be created once and reused across requests.
    async def entry(entrypoint: str) -> Markup:
        vite_dev_path = _resolve_vite_dev_path(datasette, plugin_package)
        if vite_dev_path:
            base = escape(vite_dev_path)
            return Markup(
                f'<script type="module" src="{base}@vite/client"></script>\n'
                f'<script type="module" src="{base}{escape(entrypoint)}"></script>'
            )

        manifest = _load_manifest(plugin_package, manifest_dir)
        chunk = manifest.get(entrypoint)
        if not chunk:
            raise ValueError(f"Entrypoint {entrypoint} not found in manifest")
        parts = []

        css_urls = _collect_css_urls(datasette, plugin_package, manifest, entrypoint)
        for href in css_urls:
            parts.append(Markup(f'<link rel="stylesheet" href="{escape(href)}">'))

        src = _static_url(datasette, plugin_package, chunk.file)
        parts.append(Markup(f'<script type="module" src="{escape(src)}"></script>'))

        return Markup("\n").join(parts)

    return entry


@hookimpl
def startup(datasette):
    config = datasette.plugin_config("datasette-vite") or {}
    packages = {**(config.get("dev_paths") or {}), **(config.get("dev_ports") or {})}
    if packages:
        logger.warning(
            "datasette-vite dev mode is ON for %s. Pages will load assets from a "
            "Vite dev server. Do not deploy with this setting.",
            ", ".join(sorted(packages)),
        )
