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
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/**/*.d.ts"],
      reporter: [
        "text",
        "html",
        [
          "lcov",
          { projectRoot: fileURLToPath(new URL("..", import.meta.url)) },
        ],
      ],
      reportsDirectory: fileURLToPath(
        new URL("../build/reports/coverage/frontend", import.meta.url),
      ),
    },
    reporters: ["default", "junit"],
    outputFile: {
      junit: fileURLToPath(
        new URL("../build/reports/frontend.xml", import.meta.url),
      ),
    },
  },
});
