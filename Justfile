check:
  uv run ty check

test:
  uv run pytest

build-fixtures:
  cd tests/vite-fixtures/vanilla-ts && npm install && npm run build
  cd tests/vite-fixtures/svelte-ts && npm install && npm run build
  cd tests/vite-fixtures/react-ts && npm install && npm run build
