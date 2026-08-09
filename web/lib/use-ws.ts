"use client";

// Browser WS client for live ticks/topics pushed from the Starlette /ws
// endpoint (api/ws.py) — additive to useApi (lib/use-api.ts), which stays the
// right tool for on-demand REST data (historical charts, fundamentals).
//
// A single shared WebSocket for the whole app (module-level singleton, not
// React Context — there's nothing here that needs a provider for one socket).
// Reconnects on close with a capped exponential backoff.

type TickHandler = (tick: any) => void;
type TopicHandler = (payload: any) => void;

// No symbol -> instrument-key map lives here any more. It used to mirror
// services/upstox.py, and the mirror was wrong for every equity: Upstox keys
// equities by ISIN (`NSE_EQ|INE002A01018`), so a handler registered under
// `NSE_EQ|RELIANCE` never matched an incoming tick and stock prices never
// moved on the socket. The server resolves names and echoes the caller's own
// name back on each tick.

function defaultWsUrl(): string {
  if (process.env.NEXT_PUBLIC_ARTHA_WS_URL) return process.env.NEXT_PUBLIC_ARTHA_WS_URL;
  if (typeof window !== "undefined") return `ws://${window.location.hostname}:8000/ws`;
  return "ws://localhost:8000/ws";
}

class MarketWs {
  private ws: WebSocket | null = null;
  private tickHandlers = new Map<string, Set<TickHandler>>();
  private topicHandlers = new Map<string, Set<TopicHandler>>();
  private subscribedKeys = new Set<string>();
  private reconnectDelay = 1000;

  private ensureConnected() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    const ws = new WebSocket(defaultWsUrl());
    this.ws = ws;

    ws.onopen = () => {
      this.reconnectDelay = 1000;
      if (this.subscribedKeys.size) {
        ws.send(JSON.stringify({ action: "subscribe", keys: Array.from(this.subscribedKeys) }));
      }
    };
    ws.onmessage = (ev) => {
      let msg: any;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg?.type === "tick") {
        // Handlers are registered under the caller's own name ("RELIANCE",
        // "nifty50"), which is what the server echoes back. Matching on `key`
        // alone missed every equity, whose key is its ISIN.
        //
        // `symbols` is every alias the instrument is subscribed under, because
        // two callers can name the same instrument differently and only one of
        // them used to get ticks. Dedupe the handlers: a component that
        // subscribed under two aliases must still be called once per tick.
        const names: string[] = msg.symbols?.length ? msg.symbols : [msg.symbol];
        const fire = new Set<TickHandler>();
        for (const name of [...names, msg.key]) {
          this.tickHandlers.get(name)?.forEach((h) => fire.add(h));
        }
        fire.forEach((h) => h(msg.tick));
      } else if (msg?.type) {
        this.topicHandlers.get(msg.type)?.forEach((h) => h(msg.payload));
      }
    };
    ws.onclose = () => {
      const delay = this.reconnectDelay;
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
      setTimeout(() => this.ensureConnected(), delay);
    };
    ws.onerror = () => ws.close();
  }

  subscribe(symbolsOrKeys: string[], onTick: TickHandler): () => void {
    this.ensureConnected();
    // Send the caller's names as-is — the server resolves them (equities to
    // their ISIN key) and echoes the original name back on each tick, so no
    // symbol->instrument-key mapping has to be duplicated in the browser.
    for (const name of symbolsOrKeys) {
      if (!this.tickHandlers.has(name)) this.tickHandlers.set(name, new Set());
      this.tickHandlers.get(name)!.add(onTick);
      this.subscribedKeys.add(name);
    }
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: "subscribe", keys: symbolsOrKeys }));
    }
    return () => { for (const name of symbolsOrKeys) this.tickHandlers.get(name)?.delete(onTick); };
  }

  subscribeTopic(topic: string, onMessage: TopicHandler): () => void {
    this.ensureConnected();
    if (!this.topicHandlers.has(topic)) this.topicHandlers.set(topic, new Set());
    this.topicHandlers.get(topic)!.add(onMessage);
    return () => { this.topicHandlers.get(topic)?.delete(onMessage); };
  }
}

let singleton: MarketWs | null = null;
function getMarketWs(): MarketWs {
  if (!singleton) singleton = new MarketWs();
  return singleton;
}

export function useMarketWs() {
  return {
    subscribe: (symbolsOrKeys: string[], onTick: TickHandler) => getMarketWs().subscribe(symbolsOrKeys, onTick),
    subscribeTopic: (topic: string, onMessage: TopicHandler) => getMarketWs().subscribeTopic(topic, onMessage),
  };
}
