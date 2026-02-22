import json
import pytest
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


FIXTURE_DIR = Path(__file__).parent / "vite-fixtures"


@pytest.fixture
def fixture_server():
    """Factory fixture: starts an HTTP server serving a built vite fixture's dist/ directory."""
    servers = []

    def _create(fixture_name, entrypoint, extra_body=""):
        dist_path = FIXTURE_DIR / fixture_name / "dist"
        manifest_path = dist_path / ".vite" / "manifest.json"
        if not manifest_path.exists():
            pytest.skip(f"{fixture_name} not built (run `just build-fixtures`)")

        manifest = json.loads(manifest_path.read_text())
        chunk = manifest[entrypoint]

        tags = []
        for css in chunk.get("css", []):
            tags.append(f'<link rel="stylesheet" href="/{css}">')
        tags.append(f'<script type="module" src="/{chunk["file"]}"></script>')

        html = (
            "<!DOCTYPE html>\n<html>\n<head>\n"
            + "\n".join(tags)
            + "\n</head>\n<body>\n"
            + extra_body
            + "\n</body>\n</html>"
        )

        index_path = dist_path / "_test_index.html"
        index_path.write_text(html)

        handler = partial(SimpleHTTPRequestHandler, directory=str(dist_path))
        server = HTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        servers.append((server, index_path))
        return f"http://127.0.0.1:{port}/_test_index.html"

    yield _create

    for server, index_path in servers:
        server.shutdown()
        index_path.unlink(missing_ok=True)
