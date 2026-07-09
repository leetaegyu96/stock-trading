// `/ws` 실시간 카드 브로드캐스트용 WebSocket 헬퍼 + React 훅.
// 서버는 접속 시 {"type": "cards", "data": CardSummary[]} 를 1회 보내고,
// 이후 변경분이 있을 때마다 동일 포맷으로 push 한다.
import { useEffect, useRef, useState } from "react";
import type { CardSummary } from "./types";

interface CardsMessage {
  type: "cards";
  data: CardSummary[];
}

const MIN_RECONNECT_DELAY_MS = 500;
const MAX_RECONNECT_DELAY_MS = 15_000;

function wsUrl(path: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}

/** 자동 재연결(지수 백오프)이 붙은 최소 WebSocket 클라이언트. */
export class ReconnectingSocket {
  private path: string;
  private socket: WebSocket | null = null;
  private reconnectDelay = MIN_RECONNECT_DELAY_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closedByUser = false;
  private onMessage: (msg: CardsMessage) => void;
  private onStateChange?: (connected: boolean) => void;

  constructor(
    path: string,
    onMessage: (msg: CardsMessage) => void,
    onStateChange?: (connected: boolean) => void
  ) {
    this.path = path;
    this.onMessage = onMessage;
    this.onStateChange = onStateChange;
  }

  connect(): void {
    this.closedByUser = false;
    const socket = new WebSocket(wsUrl(this.path));
    this.socket = socket;

    socket.onopen = () => {
      this.reconnectDelay = MIN_RECONNECT_DELAY_MS;
      this.onStateChange?.(true);
    };

    socket.onmessage = (event: MessageEvent<string>) => {
      try {
        const parsed = JSON.parse(event.data) as CardsMessage;
        if (parsed?.type === "cards") {
          this.onMessage(parsed);
        }
      } catch {
        // 파싱 실패한 메시지는 무시
      }
    };

    socket.onclose = () => {
      this.onStateChange?.(false);
      if (this.closedByUser) return;
      this.scheduleReconnect();
    };

    socket.onerror = () => {
      socket.close();
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, MAX_RECONNECT_DELAY_MS);
  }

  close(): void {
    this.closedByUser = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close();
  }
}

export interface CardsSocketState {
  cards: CardSummary[];
  /** WebSocket 연결 여부 — 끊기면 화면은 마지막 스냅샷 유지 + "오프라인" 표시용. */
  connected: boolean;
}

/** `/ws` 에 연결해 최신 카드 스냅샷과 연결 상태를 반환하는 훅. */
export function useCardsSocket(): CardsSocketState {
  const [cards, setCards] = useState<CardSummary[]>([]);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<ReconnectingSocket | null>(null);

  useEffect(() => {
    const socket = new ReconnectingSocket(
      "/ws",
      (msg) => setCards(msg.data),
      setConnected
    );
    socketRef.current = socket;
    socket.connect();
    return () => socket.close();
  }, []);

  return { cards, connected };
}
