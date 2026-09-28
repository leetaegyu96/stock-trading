import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

// 백엔드가 아직 없을 때: `VITE_USE_MOCK=1 npm run dev` 로 목 API 를 끼워 넣는다.
// 동적 import 라 실제 빌드에는 목 코드가 딸려 들어가지 않는다.
async function boot() {
  if (import.meta.env.VITE_USE_MOCK === "1") {
    const { installMockApi } = await import("./mocks/server");
    installMockApi();
  }
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>
  );
}

void boot();
