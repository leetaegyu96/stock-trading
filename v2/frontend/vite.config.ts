import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// v2 는 nginx 서브패스 `/stock-v2/` 로 서비스된다(SPEC §1).
// 빌드시 VITE_BASE_PATH=/stock-v2/ 를 주면 자산 경로·라우터 basename·API prefix 가
// 모두 그 값을 따라간다(api.ts / App.tsx 가 import.meta.env.BASE_URL 을 재사용).
export default defineConfig({
  plugins: [react()],
  base: process.env.VITE_BASE_PATH || "/",
  build: {
    outDir: "dist",
  },
  server: {
    // 로컬 개발: 백엔드(:8030)로 프록시. 백엔드가 없으면 VITE_USE_MOCK=1 로 목을 쓴다.
    proxy: {
      "/api": {
        target: "http://localhost:8030",
        changeOrigin: true,
      },
    },
  },
});
