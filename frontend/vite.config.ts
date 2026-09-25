import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  root: fileURLToPath(new URL(".", import.meta.url)),
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true },
  test: {
    environment: "jsdom",
    clearMocks: true,
    restoreMocks: true,
    reporters: ["default", "junit"],
    outputFile: {
      junit: fileURLToPath(
        new URL("../build/reports/frontend.xml", import.meta.url),
      ),
    },
  },
});
