import "./style.css";

// Full-page entrypoint: renders into #output on the custom template page.
// Demonstrates vite_entry() usage — the plugin owns the entire page.

const app = document.querySelector<HTMLDivElement>("#output");
if (app) {
  let count = 0;
  app.innerHTML = `
    <div class="example-page">
      <h1>Vite Full Page</h1>
      <p>This page is rendered by a custom datasette template with
      <code>vite_entry()</code> loading the JS + CSS.</p>
      <div class="counter">
        <button id="dec">-</button>
        <span id="count">0</span>
        <button id="inc">+</button>
      </div>
    </div>
  `;

  const countEl = document.getElementById("count")!;
  document.getElementById("dec")!.addEventListener("click", () => {
    countEl.textContent = String(--count);
  });
  document.getElementById("inc")!.addEventListener("click", () => {
    countEl.textContent = String(++count);
  });
}
