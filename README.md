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
    manifest: true,
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

After running `vite build`, copy `dist/.vite/manifest.json` and `dist/static/` into your plugin's Python package directory so they are included when your plugin is installed.

### Using `vite_entry()` in your plugin

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

### Development mode

During development, pass `vite_dev_path` to point at a running Vite dev server instead of reading from the manifest. This enables hot module replacement:

```python
entry = vite_entry(
    datasette=datasette,
    plugin_package="my_datasette_plugin",
    vite_dev_path="http://localhost:5173/",
)
html = await entry("src/main.ts")
```

This produces:

```html
<script type="module" src="http://localhost:5173/@vite/client"></script>
<script type="module" src="http://localhost:5173/src/main.ts"></script>
```

### API reference

`vite_entry(datasette, plugin_package, vite_dev_path=None, manifest_dir=None)`

- **`datasette`**: The Datasette instance.
- **`plugin_package`**: The Python package name of your plugin (used to resolve the manifest location and generate static asset URLs).
- **`vite_dev_path`**: Optional URL to a running Vite dev server (e.g. `"http://localhost:5173/"`). When set, assets are served from the dev server instead of from built files.
- **`manifest_dir`**: Optional path to the directory containing `manifest.json`. Defaults to the directory of your plugin package's `__init__.py`.

Returns an async callable. Call it with an entrypoint path (matching a key in your Vite manifest) to get an HTML string of the corresponding `<script>` and `<link>` tags.

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
