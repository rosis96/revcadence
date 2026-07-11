import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Local dev: `npm run dev` proxies /api to VITE_API_BASE (default: local FastAPI).
// Production: built dist/ is served by FastAPI itself — same origin, no proxy.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: process.env.VITE_API_BASE || "http://localhost:8000",
        changeOrigin: true,
      },
      "/healthz": {
        target: process.env.VITE_API_BASE || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
