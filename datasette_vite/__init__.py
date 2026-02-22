from datasette import hookimpl
from pathlib import Path
from pydantic import BaseModel
from textwrap import dedent
from typing import Awaitable, Callable, Optional
import json


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


def vite_entry(
    datasette,
    plugin_package: str,
    vite_dev_path: str | None = None,
    manifest_dir: str | Path | None = None,
) -> Callable[[str], Awaitable[str]]:
    manifest: dict[str, ManifestChunk] = {}
    if not vite_dev_path:
        if manifest_dir is None:
            mod = __import__(plugin_package)
            mod_file = mod.__file__
            assert mod_file is not None, f"Module {plugin_package} has no __file__"
            resolved_dir = Path(mod_file).parent
        else:
            resolved_dir = Path(manifest_dir)
        manifest_path = resolved_dir / "manifest.json"
        if manifest_path.exists():
            manifest_raw = json.loads(manifest_path.read_text())
            manifest = {k: ManifestChunk(**v) for k, v in manifest_raw.items()}

    async def entry(entrypoint: str) -> str:
        if vite_dev_path:
            return dedent(f"""

          <script type="module" src="{vite_dev_path}@vite/client"></script>
          <script type="module" src="{vite_dev_path}{entrypoint}"></script>

          """)

        chunk = manifest.get(entrypoint)
        if not chunk:
            raise ValueError(f"Entrypoint {entrypoint} not found in manifest")
        parts = []

        for css in chunk.css or []:
            file = str(Path(css).relative_to("static"))
            href = datasette.urls.static_plugins(plugin_package, file)
            parts.append(f'<link rel="stylesheet" href="{href}">')

        file = str(Path(chunk.file).relative_to("static"))
        src = datasette.urls.static_plugins(plugin_package, file)
        parts.append(f'<script type="module" src="{src}"></script>')

        return "\n".join(parts)

    return entry
