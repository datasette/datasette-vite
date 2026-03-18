import "./style.css";

// Content-script entrypoint: injected on every datasette page via
// extra_js_urls / extra_css_urls hooks using vite_urls().
// Demonstrates how plugins can add assets to existing pages without
// owning the template.

const banner = document.createElement("div");
banner.className = "vite-banner";
banner.innerHTML = 'datasette-vite content script loaded — <a href="/vite-demo">standalone page demo</a>';
document.body.prepend(banner);
