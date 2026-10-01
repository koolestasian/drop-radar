import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev the API runs separately (`python -m radar serve` on :8000); proxying it
// keeps one origin, so no CORS. In production FastAPI serves web/dist itself.
const api = { target: "http://127.0.0.1:8000", changeOrigin: true };

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": api, "/healthz": api } },
  preview: { proxy: { "/api": api, "/healthz": api } },
});
