from datasette import hookimpl
from datasette_vite import vite_entry, vite_js_urls, vite_css_urls


@hookimpl
async def extra_template_vars(datasette):
    entry = vite_entry(
        datasette=datasette,
        plugin_package="datasette_vite",
    )
    return {"vite_page_head": await entry("src/page/main.ts")}


@hookimpl
def extra_js_urls(datasette):
    return vite_js_urls(
        datasette=datasette,
        entrypoint="src/banner/main.ts",
        plugin_package="datasette_vite",
    )


@hookimpl
def extra_css_urls(datasette):
    return vite_css_urls(
        datasette=datasette,
        entrypoint="src/banner/main.ts",
        plugin_package="datasette_vite",
    )
