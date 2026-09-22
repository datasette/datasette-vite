# datasette-vite

[![PyPI](https://img.shields.io/pypi/v/datasette-vite.svg)](https://pypi.org/project/datasette-vite/)
[![Changelog](https://img.shields.io/github/v/release/datasette/datasette-vite?include_prereleases&label=changelog)](https://github.com/datasette/datasette-vite/releases)
[![Tests](https://github.com/datasette/datasette-vite/actions/workflows/test.yml/badge.svg)](https://github.com/datasette/datasette-vite/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/datasette/datasette-vite/blob/main/LICENSE)

Utility for writing frontend plugins for Datasette with Vite

## Installation

Install this plugin in the same environment as Datasette.
```bash
datasette install datasette-vite
```
## Usage

This plugin provides a `vite_entry()` function that other Datasette plugins can use to include Vite-built JavaScript and CSS assets in their pages.

### Setting up your plugin

Your plugin needs a Vite project alongside its Python code. Configure `vite.config.ts` to output a manifest and place built files in a `static/` directory:

```ts
// vite.config.ts
import { defineConfig } from 'vite'

export default defineConfig({
  build: {
    manifest: 'manifest.json',
    outDir: 'dist',
    rollupOptions: {
      input: 'src/main.ts',
      output: {
        assetFileNames: 'static/[name]-[hash][extname]',
        chunkFileNames: 'static/[name]-[hash].js',
        entryFileNames: 'static/[name]-[hash].js',
      }
    }
  }
})
```

Setting `manifest: 'manifest.json'` (rather than `manifest: true`) writes the manifest
to `dist/manifest.json` instead of `dist/.vite/manifest.json`, so there's one fewer
hidden directory to copy from.

After running `vite build`, copy `dist/manifest.json` and `dist/static/` into your
plugin's Python package directory so they are included when your plugin is installed.
Declare them in `pyproject.toml` so `pip install .` picks them up too:

```toml
[tool.setuptools.package-data]
your_plugin_package = ["manifest.json", "static/**/*", "templates/**/*"]
```

### Using the `vite_entry()` template function

If your plugin owns a template, this is the simplest option. datasette-vite registers a
`vite_entry()` Jinja global, so any template can render the tags for an entrypoint with no
Python hook at all:

```html+jinja
{% extends "base.html" %}

{% block extra_head %}
{{ vite_entry("my_datasette_plugin", "src/main.ts") }}
{% endblock %}
```

The arguments are the plugin package and the entrypoint; an optional third argument is the
`manifest_dir` (see the API reference). The output is the same `Markup` that the Python
`vite_entry()` factory produces below, and it follows the same dev-mode settings.

### Using `vite_entry()` in your plugin

To build the tags in Python instead (for example to pass them to a template you render
yourself), use the `vite_entry()` factory:

```python
from datasette_vite import vite_entry

entry = vite_entry(
    datasette=datasette,
    plugin_package="my_datasette_plugin",
)
html = await entry("src/main.ts")
```

The returned `html` string contains `<script>` and `<link>` tags ready to include in your page:

```html
<link rel="stylesheet" href="/-/static-plugins/my_datasette_plugin/main-def456.css">
<script type="module" src="/-/static-plugins/my_datasette_plugin/main-abc123.js"></script>
```

If the entrypoint statically imports other chunks (for example a shared vendor chunk), a
`<link rel="modulepreload">` is emitted for each of them, after the stylesheets and before
the entry script, so the browser fetches them in parallel instead of one hop at a time.
Dynamic `import()` chunks are not preloaded; Vite loads those on demand.

`html` is a [`markupsafe.Markup`](https://markupsafe.palletsprojects.com/) string with every interpolated value already escaped, so you can drop it straight into a Jinja template without `|safe`:

```html+jinja
{% block extra_head %}
{{ my_plugin_vite_head }}
{% endblock %}
```

### Development mode

During development, point your plugin at a running Vite dev server instead of reading from the manifest. This enables hot module replacement.

Configure a dev path via the `datasette-vite` plugin setting, keyed by your plugin's Python package name:

```bash
datasette \
    -s plugins.datasette-vite.dev_paths.my_datasette_plugin http://localhost:5173/
```

If your Vite config uses the default `base: '/'`, a port-only shorthand works too — datasette-vite expands it to `http://localhost:<port>/`:

```bash
datasette \
    -s plugins.datasette-vite.dev_ports.my_datasette_plugin 5173
```

Whenever any `dev_paths` or `dev_ports` entry is configured, datasette-vite logs a warning at startup naming the packages in dev mode (`datasette-vite dev mode is ON for my_datasette_plugin...`). Dev-mode pages load scripts from `localhost`, which breaks (or worse) for real visitors, so never deploy with these settings.

Your plugin code is the same in dev and prod — datasette-vite reads the setting (and the cached manifest) each time the callable returned by `vite_entry()` is awaited, not when `vite_entry()` itself is called, so `vite_entry()` can safely be called once at startup:

```python
entry = vite_entry(
    datasette=datasette,
    plugin_package="my_datasette_plugin",
)
html = await entry("src/main.ts")
```

In dev mode this produces:

```html
<script type="module" src="http://localhost:5173/@vite/client"></script>
<script type="module" src="http://localhost:5173/src/main.ts"></script>
```

### Using `vite_js_urls()` and `vite_css_urls()` for content scripts

If your plugin needs to inject assets into *existing* Datasette pages (rather than owning the full template), use `vite_js_urls()` and `vite_css_urls()`. These return structured data suitable for Datasette's `extra_js_urls` and `extra_css_urls` hooks:

```python
from datasette import hookimpl
from datasette_vite import vite_js_urls, vite_css_urls

@hookimpl
def extra_js_urls(datasette):
    return vite_js_urls(
        datasette=datasette,
        entrypoint="src/main.ts",
        plugin_package="my_datasette_plugin",
    )

@hookimpl
def extra_css_urls(datasette):
    return vite_css_urls(
        datasette=datasette,
        entrypoint="src/main.ts",
        plugin_package="my_datasette_plugin",
    )
```

Dev-mode behavior is controlled by the same `plugins.datasette-vite.dev_paths` / `dev_ports` settings described above.

`vite_js_urls()` returns a list of `{"url": "...", "module": True}` dicts. In dev mode this includes the Vite client script; in prod mode it resolves the hashed filename from the manifest. Datasette's `extra_js_urls` can only emit `<script>` tags, so content scripts do not get the `<link rel="modulepreload">` hints that `vite_entry()` emits for imported chunks; those chunks are fetched when the entry script imports them.

`vite_css_urls()` returns a list of CSS URL strings. In dev mode this returns `[]` (Vite injects CSS via JS). In prod mode it collects all CSS from the entrypoint and recursively from imported chunks.

### API reference

#### `vite_entry(datasette, plugin_package, manifest_dir=None, *, nonce=None, crossorigin=None)`

- **`datasette`**: The Datasette instance.
- **`plugin_package`**: The Python package name of your plugin (used to resolve the manifest location, generate static asset URLs, and look up dev-mode config).
- **`manifest_dir`**: Optional path to the directory containing `manifest.json`. Defaults to the directory of your plugin package's `__init__.py`.
- **`nonce`**: Optional keyword-only [CSP nonce](https://developer.mozilla.org/en-US/docs/Web/HTML/Global_attributes/nonce). When set, `nonce="..."` is added to every emitted `<script>`, `<link rel="stylesheet">` and `<link rel="modulepreload">` tag. Datasette has no built-in CSP nonce; generate one per request yourself (for example in an `asgi_wrapper` that also sets the `Content-Security-Policy` header) and pass it through.
- **`crossorigin`**: Optional keyword-only value for the `crossorigin` attribute on every emitted tag (`"anonymous"`, `"use-credentials"`, or `""` for a bare `crossorigin`). Useful when assets are served from another origin, such as a CDN or the Vite dev server; a `modulepreload` must match the `crossorigin` of the script that imports it.

When neither `nonce` nor `crossorigin` is passed, the output contains neither attribute.

Returns an async callable. Call it with an entrypoint path (matching a key in your Vite manifest) to get a `markupsafe.Markup` string of the corresponding `<script>` and `<link>` tags. All attribute values are HTML-escaped, so the result is safe to render in a Jinja template without `|safe`.

#### `{{ vite_entry(plugin_package, entrypoint, manifest_dir=None, nonce=None, crossorigin=None) }}` (Jinja global)

Available in every Datasette template. Returns the same `markupsafe.Markup` as awaiting the callable from `vite_entry()`; it is synchronous, so no `await` is needed in the template. `nonce` and `crossorigin` must be passed as keywords, e.g. `{{ vite_entry("my_plugin", "src/main.ts", nonce=csp_nonce) }}`.

#### Dev-mode resolution order

For all three functions, the dev path is resolved from `datasette.plugin_config("datasette-vite")` in this order — first match wins:

1. `dev_paths.<plugin_package>` — full URL. Must use the `http` or `https` scheme and include a host; anything else (`javascript:`, `file:`, a bare `localhost:5173`) raises `ValueError`. A trailing `/` is added if missing, so `http://localhost:5173` and `http://localhost:5173/` are equivalent.
2. `dev_ports.<plugin_package>` — port number (an integer, or a string of digits); expanded to `http://localhost:<port>/`. Non-integer or out-of-range (not 1–65535) values raise `ValueError`.
3. None — production mode; assets are read from the manifest.

#### `vite_js_urls(datasette, entrypoint, plugin_package, manifest_dir=None)`

Returns a list of URL entries suitable for Datasette's `extra_js_urls` hook. Each entry is a `{"url": "...", "module": True}` dict.

Datasette renders `extra_js_urls` entries itself and only supports the `url`, `module` and `sri` keys, so there is no way to add a `nonce` or a custom `crossorigin` to these scripts (the same applies to `vite_css_urls()` and `extra_css_urls`). If your site uses a nonce-based `script-src` Content Security Policy, render your assets from a template with `vite_entry()` instead.

#### `vite_css_urls(datasette, entrypoint, plugin_package, manifest_dir=None)`

Returns a list of CSS URL strings suitable for Datasette's `extra_css_urls` hook. Includes CSS from the entrypoint and recursively from imported chunks.

#### `ManifestError`

A `ValueError` subclass, importable from `datasette_vite`, raised when:

- the manifest file does not exist (the message names the path it looked at — usually you forgot to run `vite build` and copy `manifest.json` into your package),
- `plugin_package` has no `__file__` (for example a namespace package) and no `manifest_dir=` was passed,
- a manifest path does not start with `static/` (see the `rollupOptions.output` settings above), or contains `..` or is absolute.

A missing entrypoint key in an otherwise valid manifest still raises a plain `ValueError` (`Entrypoint ... not found in manifest`).

## Development

To set up this plugin locally, first checkout the code. You can confirm it is available like this:
```bash
cd datasette-vite
# Confirm the plugin is visible
uv run datasette plugins
```
To run the tests:
```bash
uv run pytest
```

To try the example plugin in production mode, build it first (requires Node) — the build output under `datasette_vite/` is git-ignored:
```bash
just build-example
just dev-prod
```
