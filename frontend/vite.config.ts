import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backendTarget = process.env.VITE_WORKBENCH_API_BASE || "http://127.0.0.1:8765";

export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 900
  },
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      "/api": {
        target: backendTarget,
        changeOrigin: true
      },
      "/health": {
        target: backendTarget,
        changeOrigin: true
      }
    }
  }
});
