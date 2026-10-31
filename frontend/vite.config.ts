import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The dev/preview server forwards API calls to the backend, so the whole app can be
// served from one origin (e.g. a single ngrok tunnel on port 5173).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.VITE_PROXY_TARGET || "http://127.0.0.1:8001";
  const proxy = {
    "/api": { target, changeOrigin: true, timeout: 600000, proxyTimeout: 600000 },
    "/ready": { target, changeOrigin: true },
    "/health": { target, changeOrigin: true },
  };
  return {
    plugins: [react()],
    server: { allowedHosts: true, proxy },
    preview: { allowedHosts: true, proxy },
  };
});
