import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, the FastAPI server runs on :8000 and Vite proxies API + websocket calls to it.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
