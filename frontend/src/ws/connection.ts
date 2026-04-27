import type { WsMessage } from '../types/api';

type MessageType = WsMessage['type'];
type Handler = (data: unknown) => void;

const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/live`;

const DEBUG_WS = import.meta.env.DEV;

function wsLog(...args: unknown[]) {
  if (DEBUG_WS) console.log(...args);
}
function wsWarn(...args: unknown[]) {
  if (DEBUG_WS) console.warn(...args);
}
function wsError(...args: unknown[]) {
  if (DEBUG_WS) console.error(...args);
}

const MIN_RECONNECT_MS = 1_000;
const MAX_RECONNECT_MS = 30_000;

class WebSocketManager {
  private ws: WebSocket | null = null;
  private handlers = new Map<MessageType, Set<Handler>>();
  private reconnectMs = MIN_RECONNECT_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;

  /** Connect to the WebSocket endpoint. */
  connect(): void {
    this.intentionalClose = false;
    this.cleanup();

    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      this.reconnectMs = MIN_RECONNECT_MS;
      wsLog('[WS] connected');
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WsMessage;
        const set = this.handlers.get(msg.type);
        if (set) {
          set.forEach((h) => h(msg.data));
        }
      } catch {
        wsWarn('[WS] failed to parse message', event.data);
      }
    };

    ws.onclose = () => {
      wsLog('[WS] disconnected');
      if (!this.intentionalClose) {
        this.scheduleReconnect();
      }
    };

    ws.onerror = (err) => {
      wsError('[WS] error', err);
      ws.close();
    };

    this.ws = ws;
  }

  /** Disconnect and stop reconnecting. */
  disconnect(): void {
    this.intentionalClose = true;
    this.cleanup();
  }

  /** Register a handler for a specific message type. Returns unsubscribe fn. */
  on(type: MessageType, handler: Handler): () => void {
    let set = this.handlers.get(type);
    if (!set) {
      set = new Set();
      this.handlers.set(type, set);
    }
    set.add(handler);
    return () => {
      set!.delete(handler);
    };
  }

  private scheduleReconnect(): void {
    this.reconnectTimer = setTimeout(() => {
      wsLog(`[WS] reconnecting in ${this.reconnectMs}ms ...`);
      this.connect();
    }, this.reconnectMs);

    this.reconnectMs = Math.min(this.reconnectMs * 2, MAX_RECONNECT_MS);
  }

  private cleanup(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
        this.ws.close();
      }
      this.ws = null;
    }
  }
}

/** Singleton WebSocket manager */
const wsManager = new WebSocketManager();
export default wsManager;
