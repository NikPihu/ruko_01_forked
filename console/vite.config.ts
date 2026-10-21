import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: `npm run dev` on :5173, API calls proxied to the risk engine on :8000.
// Build: `npm run build` writes dist/, which the engine serves at /console/.
const API = process.env.RUKO_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  base: "/console/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/v1": API, "/health": API, "/sim": API },
  },
});
