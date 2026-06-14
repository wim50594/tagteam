import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiBaseUrl = process.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": { target: apiBaseUrl, changeOrigin: true },
    },
    watch: {
      usePolling: true,
      interval: 100,
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 4173,
  },
});
