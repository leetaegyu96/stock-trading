#!/usr/bin/env bash
# simcore 대시보드 실행 스크립트 — 프론트(빌드) + 파이썬 백엔드(uvicorn) + 라이브 데몬을 한 번에.
#
#   ./dashboard/dashboard.sh start     # 프론트 빌드 + 백엔드 + 라이브 데몬 기동 (localhost:8000)
#   ./dashboard/dashboard.sh stop      # 백엔드·데몬 종료
#   ./dashboard/dashboard.sh restart   # 재시작
#   ./dashboard/dashboard.sh status    # 실행 여부 (백엔드·데몬 각각)
#   ./dashboard/dashboard.sh logs      # 백엔드 로그 실시간 보기 (Ctrl+C 로 빠져나옴)
#   ./dashboard/dashboard.sh logs live # 라이브 데몬 로그
#
# uvicorn 하나가 빌드된 React(dist) + REST + WebSocket 을 모두 서빙하고,
# 라이브 데몬(simcore.live run)이 장 마감마다 시세 수집·모의 매매·상태 기록을 수행한다.
# 포트 변경: PORT=9000 ./dashboard/dashboard.sh start
# 데몬 없이 백엔드만: LIVE=0 ./dashboard/dashboard.sh start
set -euo pipefail

# ── 경로 ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # .../dashboard
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND="$SCRIPT_DIR/frontend"
RUN_DIR="$SCRIPT_DIR/.run"
PID_FILE="$RUN_DIR/uvicorn.pid"
LOG_FILE="$RUN_DIR/uvicorn.log"
LIVE_PID_FILE="$RUN_DIR/live.pid"
LIVE_LOG_FILE="$RUN_DIR/live.log"
PORT="${PORT:-8000}"
LIVE="${LIVE:-1}"
APP="dashboard.backend.app:app"
LIVE_MOD="simcore.live"

# ── uvicorn 실행기 결정 (repo venv 우선) ──
if [ -x "$REPO/.venv-linux/bin/uvicorn" ]; then
  UVICORN="$REPO/.venv-linux/bin/uvicorn"
elif [ -x "$REPO/.venv/bin/uvicorn" ]; then
  UVICORN="$REPO/.venv/bin/uvicorn"
elif command -v uvicorn >/dev/null 2>&1; then
  UVICORN="uvicorn"
else
  UVICORN=""
fi

# ── 파이썬 실행기 결정 (라이브 데몬용 — uvicorn 과 같은 venv) ──
if [ -x "$REPO/.venv-linux/bin/python" ]; then
  PYTHON="$REPO/.venv-linux/bin/python"
elif [ -x "$REPO/.venv/bin/python" ]; then
  PYTHON="$REPO/.venv/bin/python"
else
  PYTHON="python3"
fi

# ── 색 ──
c_ok=$'\033[32m'; c_warn=$'\033[33m'; c_err=$'\033[31m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
say()  { echo "${c_dim}[dashboard]${c_off} $*"; }
ok()   { echo "${c_ok}✓${c_off} $*"; }
warn() { echo "${c_warn}!${c_off} $*"; }
die()  { echo "${c_err}✗ $*${c_off}" >&2; exit 1; }

is_running() {
  [ -f "$PID_FILE" ] || return 1
  local pid; pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

live_is_running() {
  [ -f "$LIVE_PID_FILE" ] || return 1
  local pid; pid="$(cat "$LIVE_PID_FILE" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

start_live() {
  if live_is_running; then
    warn "라이브 데몬 이미 실행 중 (PID $(cat "$LIVE_PID_FILE"))"
    return 0
  fi
  mkdir -p "$RUN_DIR"
  say "라이브 데몬 기동 중 (simcore.live run — 밀린 마감 catch-up 후 스케줄러)…"
  cd "$REPO"
  nohup "$PYTHON" -u -m "$LIVE_MOD" run > "$LIVE_LOG_FILE" 2>&1 &
  echo $! > "$LIVE_PID_FILE"
  sleep 2
  if live_is_running; then
    ok "라이브 데몬 실행됨 (PID $(cat "$LIVE_PID_FILE"))  ${c_dim}로그: ./dashboard/dashboard.sh logs live${c_off}"
  else
    echo "--- 데몬 로그 ---"; tail -n 20 "$LIVE_LOG_FILE" 2>/dev/null
    warn "라이브 데몬 기동 실패 — 대시보드(저장 데이터 조회)는 계속 동작합니다."
    rm -f "$LIVE_PID_FILE"
  fi
}

stop_live() {
  if ! live_is_running; then
    if pgrep -f "[-]m $LIVE_MOD run" >/dev/null 2>&1; then
      pkill -INT -f "[-]m $LIVE_MOD run" 2>/dev/null || true
      ok "잔여 라이브 데몬 프로세스를 정리했습니다."
    fi
    rm -f "$LIVE_PID_FILE"
    return 0
  fi
  local pid; pid="$(cat "$LIVE_PID_FILE")"
  say "라이브 데몬 종료 중 (PID $pid)…"
  kill -INT "$pid" 2>/dev/null || true          # SIGINT → 스케줄러 정상 shutdown
  for _ in $(seq 1 10); do kill -0 "$pid" 2>/dev/null || break; sleep 0.3; done
  kill -0 "$pid" 2>/dev/null && kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 5); do kill -0 "$pid" 2>/dev/null || break; sleep 0.3; done
  kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
  rm -f "$LIVE_PID_FILE"
  ok "라이브 데몬 종료 완료."
}

build_frontend() {
  command -v npm >/dev/null 2>&1 || die "npm 을 찾을 수 없습니다 (Node 설치 필요)."
  cd "$FRONTEND"
  if [ ! -d node_modules ]; then
    say "프론트 의존성 설치 중 (npm install)…"
    npm install >/dev/null 2>&1 || die "npm install 실패"
  fi
  say "프론트 빌드 중 (npm run build)…"
  npm run build >/dev/null 2>&1 || die "프론트 빌드 실패 — 'cd dashboard/frontend && npm run build' 로 원인 확인"
  ok "프론트 빌드 완료 (dist)"
  cd "$REPO"
}

start() {
  if is_running; then
    warn "이미 실행 중입니다 (PID $(cat "$PID_FILE"))  →  http://localhost:$PORT"
    return 0
  fi
  [ -n "$UVICORN" ] || die "uvicorn 을 찾을 수 없습니다. 백엔드 의존성을 설치하세요 (pip install -e .[dev] + fastapi/uvicorn)."
  [ -f "$REPO/.env" ] || warn ".env 가 없습니다 — DB 접속 정보(DATABASE_URL) 없이 뜨면 데이터가 안 보일 수 있어요."

  build_frontend
  mkdir -p "$RUN_DIR"

  say "백엔드 기동 중 (uvicorn, :$PORT)…"
  cd "$REPO"
  nohup "$UVICORN" "$APP" --host 0.0.0.0 --port "$PORT" > "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"

  # 헬스 체크 (최대 ~10초 대기)
  local booted=1
  for _ in $(seq 1 20); do
    if curl -sf "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
      ok "대시보드 실행됨  →  ${c_ok}http://localhost:$PORT${c_off}   (PID $(cat "$PID_FILE"))"
      say "종료: ./dashboard/dashboard.sh stop   |   로그: ./dashboard/dashboard.sh logs"
      booted=0; break
    fi
    is_running || { echo "--- 로그 ---"; tail -n 20 "$LOG_FILE" 2>/dev/null; die "기동 실패 (로그 확인: $LOG_FILE)"; }
    sleep 0.5
  done
  [ "$booted" -eq 0 ] || warn "헬스체크 응답이 늦습니다. 로그를 확인하세요: $LOG_FILE"

  # 라이브 데몬 동시 기동 (LIVE=0 이면 생략)
  if [ "$LIVE" = "1" ]; then
    start_live
  else
    say "LIVE=0 — 라이브 데몬은 기동하지 않습니다."
  fi
}

stop() {
  stop_live
  if ! is_running; then
    # pidfile 이 없거나 죽은 경우에도 혹시 남은 프로세스 정리
    if pgrep -f "uvicorn .*$APP" >/dev/null 2>&1; then
      pkill -f "uvicorn .*$APP" 2>/dev/null || true
      ok "잔여 백엔드 프로세스를 정리했습니다."
    else
      say "실행 중이 아닙니다."
    fi
    rm -f "$PID_FILE"
    return 0
  fi
  local pid; pid="$(cat "$PID_FILE")"
  say "백엔드 종료 중 (PID $pid)…"
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 10); do kill -0 "$pid" 2>/dev/null || break; sleep 0.3; done
  kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
  rm -f "$PID_FILE"
  ok "종료 완료."
}

status() {
  if is_running; then
    ok "백엔드 실행 중 (PID $(cat "$PID_FILE"))  →  http://localhost:$PORT"
  else
    say "백엔드 정지 상태."
  fi
  if live_is_running; then
    ok "라이브 데몬 실행 중 (PID $(cat "$LIVE_PID_FILE"))"
  else
    say "라이브 데몬 정지 상태."
  fi
}

logs() {
  if [ "${1:-}" = "live" ]; then
    [ -f "$LIVE_LOG_FILE" ] || die "데몬 로그 파일이 없습니다 (아직 실행한 적 없음): $LIVE_LOG_FILE"
    tail -f "$LIVE_LOG_FILE"
    return
  fi
  [ -f "$LOG_FILE" ] || die "로그 파일이 없습니다 (아직 실행한 적 없음): $LOG_FILE"
  tail -f "$LOG_FILE"
}

case "${1:-}" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; start ;;
  status)  status ;;
  logs)    logs "${2:-}" ;;
  *) echo "사용법: $0 {start|stop|restart|status|logs [live]}   (포트: PORT=9000 $0 start / 데몬 제외: LIVE=0 $0 start)"; exit 1 ;;
esac
