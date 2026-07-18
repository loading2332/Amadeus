import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  base: "/static/",
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          const path = id.replaceAll("\\", "/");
          if (!path.includes("node_modules")) return undefined;
          if (path.includes("/@mui/") || path.includes("/@emotion/")) return "material";
          if (/\/node_modules\/(react|react-dom|scheduler)\//.test(path)) return "react";
          if (path.includes("/@tanstack/") || path.includes("/zustand/") || path.includes("/axios/")) return "data";
          return undefined;
        },
      },
    },
  },
  server: {
    proxy: {
      "/api": {
        target: process.env.AMADEUS_API_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: false,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
    css: true,
    globals: true,
  },
});
