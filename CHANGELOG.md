# Changelog

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
