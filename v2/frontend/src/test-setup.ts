// vitest(jsdom) 공통 셋업. 테스트마다 DOM 을 깨끗이 비워, 앞 테스트가 남긴 노드가
// 다음 테스트의 쿼리에 걸리는 사고를 막는다.
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
