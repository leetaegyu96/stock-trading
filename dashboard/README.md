# simcore 대시보드

라이브 데몬(`simcore.live run`)이 쌓은 상태·거래내역을 웹으로 조회/모니터링하는 대시보드.
백엔드(FastAPI)와 프론트(React + Vite)로 구성되며, 라이브 데몬과 **동일한 PostgreSQL**(`DATABASE_URL`)을 읽는다.

## 구조
- `backend/` — FastAPI 앱. REST(카드/상세/차트/표/지표/입출금 예약) + WebSocket(실시간 갱신) + 빌드된 SPA 서빙.
- `frontend/` — React SPA. 메인(카드+실시간), 상세(차트·표·지표), 입출금 모달.

## 실행
    cd frontend && npm install && npm run build   # dist/ 생성
    cd ..
    uvicorn dashboard.backend.app:app              # http://localhost:8000

- `dist/`가 있으면 백엔드가 `/`에서 SPA를 그대로 서빙한다.
- KIS 실시세를 최신 종가에 병합해 카드/차트에 반영하고, WebSocket으로 변경분만 push한다.
- 입출금 버튼으로 다음 개장 반영분을 예약할 수 있다(`simcore.live deposit/withdraw`와 동일 경로).

## 테스트
    python -m pytest dashboard/backend
    cd frontend && npm test
