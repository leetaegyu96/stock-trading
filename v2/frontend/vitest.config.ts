import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    // 컴포넌트 상호작용(수량 스테퍼·확인 모달·버튼 비활성)을 실제로 눌러 보려면
    // DOM 이 필요하다 — v1 의 renderToStaticMarkup 방식보다 한 단계 더 검증한다.
    environment: "jsdom",
    globals: false,
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    setupFiles: ["./src/test-setup.ts"],
  },
});
