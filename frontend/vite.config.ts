import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    // Dev-server proxy so the browser can call the FastAPI backend
    // (deploy/run-local.sh's BACKEND_HOST_PORT default) same-origin.
    proxy: {
      "/projects": "http://localhost:8000",
      "/characters": "http://localhost:8000",
      "/voices": "http://localhost:8000",
      "/segments": "http://localhost:8000",
      "/generation-status": "http://localhost:8000",
    },
  },
})
