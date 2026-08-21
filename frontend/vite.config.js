import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend URL is read from VITE_API_BASE at build/runtime; in dev we proxy /api.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
