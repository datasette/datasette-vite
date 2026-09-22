check:
  uv run ty check

test:
  uv run pytest

build-fixtures:
  cd tests/vite-fixtures/vanilla-ts && npm ci && npm run build
  cd tests/vite-fixtures/svelte-ts && npm ci && npm run build
  cd tests/vite-fixtures/react-ts && npm ci && npm run build

dev *flags:
  uv run datasette \
    --plugins-dir example/plugins \
    --template-dir example/templates \
    --root \
    -s plugins.datasette-vite.dev_paths.datasette_vite http://localhost:5174/ \
    {{flags}}

dev-vite *flags:
  npm run dev --prefix example {{flags}}

build-example:
  npm run build --prefix example
  rm -rf datasette_vite/static
  cp -R example/dist/static datasette_vite/static
  cp example/dist/manifest.json datasette_vite/manifest.json

dev-prod *flags:
  uv run datasette \
    --plugins-dir example/plugins \
    --template-dir example/templates \
    --root \
    {{flags}}
