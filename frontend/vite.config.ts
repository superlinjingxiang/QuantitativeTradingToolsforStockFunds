import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  root: "frontend",
  base: "./",
  plugins: [vue()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          vue: ["vue", "pinia", "vue-router"],
          charts: ["echarts"],
        },
      },
    },
  },
  server: { host: "127.0.0.1", port: 5173, strictPort: true },
});
