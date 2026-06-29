import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Test-only config. Component tests need a DOM (jsdom); the store reducer tests
// are infra-free and run fine in the same environment. No backend, no socket,
// no Docker — synthetic events drive everything.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    css: false,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
