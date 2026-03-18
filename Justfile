check:
  uv run ty check

test:
  uv run pytest

build-fixtures:
  cd tests/vite-fixtures/vanilla-ts && npm install && npm run build
  cd tests/vite-fixtures/svelte-ts && npm install && npm run build
  cd tests/vite-fixtures/react-ts && npm install && npm run build

dev *flags:
  VITE_DEV_PATH="http://localhost:5174/" \
    uv run datasette \
      --plugins-dir example/plugins \
      --template-dir example/templates \
      --root \
      {{flags}}

dev-vite *flags:
  npm run dev --prefix example {{flags}}
