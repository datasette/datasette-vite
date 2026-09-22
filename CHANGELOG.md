# Changelog

## Unreleased

- New `ManifestError` exception (a `ValueError` subclass, exported from `datasette_vite`). Existing `except ValueError` / `pytest.raises(ValueError)` code keeps working.
- A missing `manifest.json` now raises `ManifestError("Vite manifest not found at <path>...")` instead of the misleading `Entrypoint ... not found in manifest`. `vite_entry()` raises it when the returned callable is awaited.
- Manifest paths that don't start with `static/` (e.g. Vite's default `assets/`) or that contain `..` now raise `ManifestError` with an actionable message instead of a cryptic `relative_to` error.
- Dotted `plugin_package` names (e.g. `mycompany.datasette_thing`) now resolve the manifest in the leaf package directory rather than the top-level package.
- A namespace package without `__file__` now raises `ManifestError` (previously an `assert`, stripped under `python -O`).
- **Return type change:** the callable returned by `vite_entry()` now returns `markupsafe.Markup` instead of `str`, with every interpolated URL and entrypoint HTML-escaped. `Markup` is a `str` subclass, so existing string handling and `|safe` filters keep working; you can now drop `|safe` from templates. The dev-mode output no longer has leading/trailing blank lines.
- `markupsafe` is now a declared dependency (it was already installed via Jinja2).
- `dev_paths` values are now validated: they must be `http(s)://` URLs with a host, and a missing trailing `/` is added (previously `http://localhost:5173` produced the broken URL `http://localhost:5173@vite/client`). `dev_ports` values must be integers (or digit strings) in 1–65535. Invalid values raise `ValueError`.
- `vite_css_urls()` and `vite_entry()` no longer emit duplicate stylesheet URLs when chunks share a CSS file or an imported chunk imports the entrypoint back.
- Parsed manifests are now cached per manifest path and modification time, so `vite_js_urls()` / `vite_css_urls()` in `extra_js_urls` / `extra_css_urls` hooks no longer re-read and re-parse `manifest.json` on every page render. A rebuilt manifest is picked up without a restart.
- The callable returned by `vite_entry()` now resolves the dev-mode setting and loads the manifest each time it is awaited, rather than once when `vite_entry()` is called. It is now safe to create it once (e.g. in a `startup` hook) and reuse it. As a consequence, errors such as a missing manifest are raised when the callable is awaited, not by `vite_entry()` itself.
- datasette-vite now logs a warning at startup when any `dev_paths` / `dev_ports` entry is configured, naming the packages in dev mode, so dev settings accidentally left in a deployed config are visible in the logs.
- New `vite_entry(plugin_package, entrypoint)` Jinja global, registered via `prepare_jinja2_environment`, so templates can write `{{ vite_entry("my_plugin", "src/main.ts") }}` without an `extra_template_vars` hook. The `vite_entry()` Python factory is unchanged.
- `vite_entry()` (and the Jinja global) now emits `<link rel="modulepreload">` for every chunk in the entrypoint's transitive static `imports`, between the stylesheet links and the entry script, as the Vite backend-integration guide recommends. `dynamicImports` are not preloaded. `vite_js_urls()` cannot carry preload hints.

## 0.0.1a4

**Breaking change.** The `vite_dev_path` keyword argument has been removed from `vite_entry()`, `vite_js_urls()`, and `vite_css_urls()`. Dev-mode URLs are now resolved exclusively from the `datasette-vite` plugin setting.

### What's gone

- `vite_entry(..., vite_dev_path=...)` — argument removed.
- `vite_js_urls(..., vite_dev_path=...)` — argument removed.
- `vite_css_urls(..., vite_dev_path=...)` — argument removed.

Plugins that pass `vite_dev_path=` will fail with `TypeError: ... got an unexpected keyword argument 'vite_dev_path'`.

### How to upgrade

For each plugin that depends on `datasette-vite`:

**1. Python** — drop the `vite_dev_path=` argument and the env-var lookup that fed it. For example:

```diff
-import os
-
-VITE_DEV_PATH = os.environ.get("DATASETTE_MY_PLUGIN_VITE_PATH")
-
 @hookimpl
 def extra_template_vars(datasette):
     return {
         "my_plugin_vite_entry": vite_entry(
             datasette=datasette,
             plugin_package="datasette_my_plugin",
-            vite_dev_path=VITE_DEV_PATH,
         ),
     }
```

**2. Justfile / dev runner** — replace the per-plugin env var with a Datasette setting:

```diff
 dev-with-hmr *flags:
-    DATASETTE_MY_PLUGIN_VITE_PATH=http://localhost:{{DEV_PORT}}/ \
     watchexec \
         --stop-signal SIGKILL \
         -e py,html \
         --ignore '*.db' \
         --restart \
         --clear -- \
-        just dev {{flags}}
+        just dev \
+            -s plugins.datasette-vite.dev_paths.datasette_my_plugin "http://localhost:{{DEV_PORT}}/" \
+            {{flags}}
```

If your Vite config uses `base: '/'` (the default), the port-only shorthand is shorter:

```bash
-s plugins.datasette-vite.dev_ports.datasette_my_plugin {{DEV_PORT}}
```

### Resolution order

`datasette-vite` reads `datasette.plugin_config("datasette-vite")` and consults, in order:

1. `dev_paths.<plugin_package>` — full URL (e.g. `http://localhost:5173/-/static-plugins/datasette_my_plugin/`).
2. `dev_ports.<plugin_package>` — port number; expanded to `http://localhost:<port>/`.
3. Otherwise: production mode, assets are read from the manifest.

### Why

Every consumer plugin had its own boilerplate `os.environ.get("DATASETTE_<NAME>_VITE_PATH")` line, with inconsistent env var naming (`_VITE_PATH` vs `_VITE_DEV`) and per-plugin port constants that occasionally clashed when sibling plugins ran together. Centralizing dev-mode config in a single Datasette plugin setting removes the boilerplate and puts all dev URLs in one CLI flag.
