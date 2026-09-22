from datasette import hookimpl
from datasette_vite import vite_js_urls, vite_css_urls


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
