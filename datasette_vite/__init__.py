from datasette import hookimpl
from datasette.plugins import pm
from datasette.utils.asgi import Response
from markupsafe import Markup, escape
from pathlib import Path
from pydantic import BaseModel
from typing import Awaitable, Callable, Optional
from urllib.parse import urlencode, urlsplit
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


def _react_preamble_js(vite_dev_path: str) -> str:
    """The @vitejs/plugin-react preamble, per Vite's backend-integration guide."""
    # JSON-encode the URL as a JS string; escape "<" so it can't close a <script>.
    runtime = json.dumps(f"{vite_dev_path}@react-refresh").replace("<", "\\u003c")
    return (
        f"import RefreshRuntime from {runtime}\n"
        "RefreshRuntime.injectIntoGlobalHook(window)\n"
        "window.$RefreshReg$ = () => {}\n"
        "window.$RefreshSig$ = () => (type) => type\n"
        "window.__vite_plugin_react_preamble_installed__ = true\n"
    )


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


def _collect_urls(
    datasette,
    plugin_package: str,
    manifest: dict[str, ManifestChunk],
    entrypoint: str,
) -> tuple[list[str], list[str]]:
    """Walk the entrypoint's static imports depth-first.

    Returns (css_urls, preload_urls): the CSS of the entry and every transitively
    imported chunk, and the JS files of the imported chunks (excluding the entry).
    dynamicImports are not followed; Vite loads those at runtime.
    """
    css_urls: list[str] = []
    preload_urls: list[str] = []
    seen_chunks: set[str] = set()
    seen_urls: set[str] = set()

    def visit(chunk_key: str) -> None:
        if chunk_key in seen_chunks:
            return
        seen_chunks.add(chunk_key)
        chunk = manifest.get(chunk_key)
        if not chunk:
            return
        if chunk_key != entrypoint:
            url = _static_url(datasette, plugin_package, chunk.file)
            if url not in seen_urls:
                seen_urls.add(url)
                preload_urls.append(url)
        for css in chunk.css or []:
            url = _static_url(datasette, plugin_package, css)
            if url not in seen_urls:
                seen_urls.add(url)
                css_urls.append(url)
        for imp in chunk.imports or []:
            visit(imp)

    visit(entrypoint)
    return css_urls, preload_urls


def vite_js_urls(
    datasette,
    entrypoint: str,
    plugin_package: str,
    manifest_dir: str | Path | None = None,
    *,
    react: bool = False,
) -> list:
    vite_dev_path = _resolve_vite_dev_path(datasette, plugin_package)
    if vite_dev_path:
        urls = [
            {"url": f"{vite_dev_path}@vite/client", "module": True},
            {"url": f"{vite_dev_path}{entrypoint}", "module": True},
        ]
        if react:
            preamble = datasette.urls.path(
                "-/vite/react-preamble.js?"
                + urlencode({"plugin_package": plugin_package})
            )
            urls.insert(0, {"url": preamble, "module": True})
        return urls
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
    css_urls, _ = _collect_urls(datasette, plugin_package, manifest, entrypoint)
    return css_urls


def _tag_attrs(nonce: str | None, crossorigin: str | None) -> Markup:
    attrs = Markup("")
    if nonce is not None:
        attrs += Markup(' nonce="{}"').format(nonce)
    if crossorigin == "":
        attrs += Markup(" crossorigin")
    elif crossorigin is not None:
        attrs += Markup(' crossorigin="{}"').format(crossorigin)
    return attrs


def _render_entry(
    datasette,
    plugin_package: str,
    entrypoint: str,
    manifest_dir: str | Path | None = None,
    *,
    nonce: str | None = None,
    crossorigin: str | None = None,
    react: bool = False,
) -> Markup:
    attrs = _tag_attrs(nonce, crossorigin)
    vite_dev_path = _resolve_vite_dev_path(datasette, plugin_package)
    if vite_dev_path:
        base = escape(vite_dev_path)
        html = Markup(
            f'<script type="module" src="{base}@vite/client"{attrs}></script>\n'
            f'<script type="module" src="{base}{escape(entrypoint)}"{attrs}></script>'
        )
        if react:
            # Inline script: crossorigin does not apply, only the nonce.
            preamble = Markup(
                f'<script type="module"{_tag_attrs(nonce, None)}>\n'
                f"{_react_preamble_js(vite_dev_path)}</script>\n"
            )
            html = preamble + html
        return html

    manifest = _load_manifest(plugin_package, manifest_dir)
    chunk = manifest.get(entrypoint)
    if not chunk:
        raise ValueError(f"Entrypoint {entrypoint} not found in manifest")
    parts = []

    css_urls, preload_urls = _collect_urls(
        datasette, plugin_package, manifest, entrypoint
    )
    for href in css_urls:
        parts.append(Markup(f'<link rel="stylesheet" href="{escape(href)}"{attrs}>'))
    for href in preload_urls:
        parts.append(
            Markup(f'<link rel="modulepreload" href="{escape(href)}"{attrs}>')
        )

    src = _static_url(datasette, plugin_package, chunk.file)
    parts.append(
        Markup(f'<script type="module" src="{escape(src)}"{attrs}></script>')
    )

    return Markup("\n").join(parts)


def vite_entry(
    datasette,
    plugin_package: str,
    manifest_dir: str | Path | None = None,
    *,
    nonce: str | None = None,
    crossorigin: str | None = None,
    react: bool = False,
) -> Callable[[str], Awaitable[Markup]]:
    # Config and manifest are resolved on every call (the manifest is cached), so
    # the returned callable can be created once and reused across requests.
    async def entry(entrypoint: str) -> Markup:
        return _render_entry(
            datasette,
            plugin_package,
            entrypoint,
            manifest_dir,
            nonce=nonce,
            crossorigin=crossorigin,
            react=react,
        )

    return entry


@hookimpl
def prepare_jinja2_environment(env, datasette):
    def vite_entry_global(
        plugin_package: str,
        entrypoint: str,
        manifest_dir: str | Path | None = None,
        *,
        nonce: str | None = None,
        crossorigin: str | None = None,
        react: bool = False,
    ) -> Markup:
        return _render_entry(
            datasette,
            plugin_package,
            entrypoint,
            manifest_dir,
            nonce=nonce,
            crossorigin=crossorigin,
            react=react,
        )

    env.globals["vite_entry"] = vite_entry_global


async def _react_preamble_view(datasette, request):
    # The dev path comes from server-side config, never from the request, so
    # nothing user-supplied is reflected into the script.
    plugin_package = request.args.get("plugin_package") or ""
    vite_dev_path = _resolve_vite_dev_path(datasette, plugin_package)
    if not vite_dev_path:
        return Response.text("Not found", status=404)
    return Response(
        _react_preamble_js(vite_dev_path),
        content_type="text/javascript; charset=utf-8",
    )


# specname lets this coexist with other register_routes implementations here.
@hookimpl(specname="register_routes")
def register_react_preamble_route(datasette):
    return [(r"^/-/vite/react-preamble\.js$", _react_preamble_view)]


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


# /-/vite diagnostics page. Read-only; shows per known package what datasette-vite
# resolved (mode, dev URL or config error, manifest path/presence, entrypoints).
# Gated on "view-instance" + "debug-menu": "view-instance" alone is in Datasette's
# DEFAULT_ALLOW_ACTIONS and so is granted to anonymous actors, while "debug-menu"
# is what Datasette's own default_debug_menu.py uses to surface its debug pages.


async def _vite_ensure_diagnostics_permission(datasette, actor):
    await datasette.ensure_permission(action="view-instance", actor=actor)
    await datasette.ensure_permission(action="debug-menu", actor=actor)


def _vite_known_packages(datasette) -> dict[str, Path | None]:
    """Return {package: manifest_dir} for every package datasette-vite knows
    about: the union of configured dev_paths/dev_ports keys, and every
    installed plugin whose package directory contains a manifest.json.

    `manifest_dir` is the directory to pass straight through as manifest_dir=
    (bypassing package import) for packages discovered by scanning plugin
    module files; it is None for config-only entries, which fall back to
    _manifest_path()'s usual "import the package" behavior.
    """
    config = datasette.plugin_config("datasette-vite") or {}
    packages: dict[str, Path | None] = {
        name: None
        for name in {
            **(config.get("dev_paths") or {}),
            **(config.get("dev_ports") or {}),
        }
    }
    for plugin in pm.get_plugins():
        name = getattr(plugin, "__name__", None) or plugin.__class__.__name__
        mod_file = getattr(plugin, "__file__", None)
        if not mod_file:
            continue
        plugin_dir = Path(mod_file).parent
        if (plugin_dir / "manifest.json").exists():
            packages[name] = plugin_dir
    return packages


def _vite_package_diagnostics(
    datasette, package: str, manifest_dir: Path | None
) -> dict:
    config = datasette.plugin_config("datasette-vite") or {}
    dev_configured = package in (config.get("dev_paths") or {}) or package in (
        config.get("dev_ports") or {}
    )
    row = {
        "package": package,
        "mode": "dev" if dev_configured else "prod",
        "dev_url": None,
        "dev_error": None,
        "manifest_path": None,
        "manifest_found": False,
        "entrypoints": [],
    }
    if dev_configured:
        try:
            row["dev_url"] = _resolve_vite_dev_path(datasette, package)
        except ValueError as exc:
            row["dev_error"] = str(exc)

    try:
        manifest_path = _manifest_path(package, manifest_dir)
    except (ManifestError, ImportError):
        return row
    row["manifest_path"] = str(manifest_path)
    row["manifest_found"] = manifest_path.exists()
    if row["manifest_found"]:
        try:
            manifest = _load_manifest(package, manifest_dir)
        except (ManifestError, ImportError):
            pass
        else:
            row["entrypoints"] = sorted(
                key for key, chunk in manifest.items() if chunk.isEntry
            )
    return row


def _vite_diagnostics_rows(datasette) -> list[dict]:
    packages = _vite_known_packages(datasette)
    return [
        _vite_package_diagnostics(datasette, package, manifest_dir)
        for package, manifest_dir in sorted(packages.items())
    ]


async def _vite_diagnostics_view(datasette, request):
    await _vite_ensure_diagnostics_permission(datasette, request.actor)
    rows = _vite_diagnostics_rows(datasette)
    dev_mode = any(row["mode"] == "dev" for row in rows)
    if request.url_vars.get("format") == "json":
        return Response.json({"ok": True, "dev_mode": dev_mode, "packages": rows})
    return Response.html(
        await datasette.render_template(
            "vite.html",
            {"packages": rows, "dev_mode": dev_mode},
            request=request,
        )
    )


@hookimpl
def register_routes():
    return [
        (r"^/-/vite(\.(?P<format>json))?$", _vite_diagnostics_view),
    ]


@hookimpl
def menu_links(datasette, actor):
    async def inner():
        if not await datasette.allowed(
            action="view-instance", actor=actor
        ) or not await datasette.allowed(action="debug-menu", actor=actor):
            return []
        return [
            {
                "href": datasette.urls.path("/-/vite"),
                "label": "Vite diagnostics",
            }
        ]

    return inner
