import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Development: the React app on :5173 talks to the backend on :8000 through this proxy, so the browser
// only ever sees one origin. (changeOrigin stays false on purpose: the backend checks Host against Origin.)
// Production: the backend serves the built app itself, so there is nothing to proxy.
const BACKEND = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: BACKEND },
      "/bundle": { target: BACKEND },
    },
  },
});
