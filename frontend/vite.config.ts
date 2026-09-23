import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The browser only ever talks to its own origin; the dev server forwards /api
// to the FastAPI process, the way a CDN or load balancer will in production.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.SIFT_API_URL ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
