import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server runs on 5173. Requests to /api are proxied to the
// FastAPI backend (api.py) on localhost:8000 so there are no CORS
// issues and the frontend code never hardcodes the backend URL.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true, // listen on all interfaces (IPv4 + IPv6) so the browser can reach it
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
