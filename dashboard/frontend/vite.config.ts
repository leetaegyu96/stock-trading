import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // 서브패스 배포 지원: 빌드시 VITE_BASE_PATH=/foo/ 로 지정하면 자산 경로가
  // 그 프리픽스를 갖도록 빌드된다. 기본은 루트("/") 배포.
  base: process.env.VITE_BASE_PATH || "/",
  build: {
    outDir: "dist",
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "http://localhost:8000",
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
