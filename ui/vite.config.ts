import { defineConfig } from "vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import viteReact from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import tsConfigPaths from "vite-tsconfig-paths";

// Self-hosted Vite config: @ path alias (tsconfig paths), Tailwind v4,
// TanStack Start and React. SPA mode — the app is served as static files by
// the FastAPI backend (`eeze ui build` -> ui/dist/client), so there is no
// SSR/nitro server target.
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
      },
    },
  },
  plugins: [tsConfigPaths(), tailwindcss(), tanstackStart({ spa: { enabled: true } }), viteReact()],
});
