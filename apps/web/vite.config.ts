import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // One .env at the repo root, shared with the API. Only VITE_* reaches the browser.
  envDir: "../..",
  server: { port: 5173, strictPort: true },
});
