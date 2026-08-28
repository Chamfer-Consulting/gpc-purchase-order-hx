import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: { port: 5173 },
  build: {
    outDir: "dist",
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          echarts: ["echarts", "echarts-for-react"],
          mantine: ["@mantine/core", "@mantine/hooks", "@mantine/dates"],
        },
      },
    },
  },
});
