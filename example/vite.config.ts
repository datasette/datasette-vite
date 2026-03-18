import { defineConfig } from "vite";

export default defineConfig({
  server: {
    cors: true,
  },
  build: {
    manifest: "manifest.json",
    outDir: "dist",
    rollupOptions: {
      input: {
        page: "src/page/main.ts",
        banner: "src/banner/main.ts",
      },
      output: {
        assetFileNames: "static/[name]-[hash][extname]",
        chunkFileNames: "static/[name]-[hash].js",
        entryFileNames: "static/[name]-[hash].js",
      },
    },
  },
});
