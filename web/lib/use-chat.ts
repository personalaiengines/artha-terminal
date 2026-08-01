"use client";
import { useCallback, useEffect, useRef, useState } from "react";

// Conversation state + SSE transport for the AI analyst.
//
// Replaces the old page-local flow, which posted only `{q}` (so every message
// was context-free — the "What are the risks?" follow-up chip had nothing to
// attach to), waited for the whole answer, then replayed it through a fake
// typewriter. This streams real tokens, keeps history, and holds multiple
// threads so a portfolio question doesn't bleed into a stock deep dive.

export type ChatStatus = { stage: string; label?: string; intent?: string; symbols?: string[] };
export type ChatMsg = {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  error?: boolean;
  stopped?: boolean;
  intent?: string;
  cards?: string[];
  sources?: string[];
  steps?: ChatStatus[];
};
export type Thread = { id: string; title: string; updatedAt: number; messages: ChatMsg[] };

const KEY = "artha:chat:v2";
const MAX_THREADS = 30;
const MAX_MSGS = 60;

const newId = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
const titleFrom = (q: string) => (q.length > 44 ? `${q.slice(0, 44).trimEnd()}…` : q);

// Native EventSource can't POST, so read the SSE body off fetch directly.
async function* sseEvents(res: Response, signal: AbortSignal) {
  const reader = res.body!.getReader();
  const dec = new TextDecoder();
  let buf = "";
  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      // Frames are separated by a blank line; keep any partial tail in `buf`.
      const frames = buf.split("\n\n");
      buf = frames.pop() ?? "";
      for (const frame of frames) {
        let event = "message";
        const data: string[] = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) data.push(line.slice(5).trim());
        }
        if (!data.length) continue;
        try {
          yield { event, payload: JSON.parse(data.join("\n")) };
        } catch {
          /* keep the stream alive through one malformed frame */
        }
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}

export function useChat() {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<ChatStatus | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const loaded = useRef(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) {
        const saved = JSON.parse(raw);
        setThreads(saved.threads ?? []);
        setActiveId(saved.activeId ?? saved.threads?.[0]?.id ?? null);
      }
    } catch { /* corrupt entry — start clean */ }
    loaded.current = true;
  }, []);

  useEffect(() => {
    if (!loaded.current) return;
    try {
      localStorage.setItem(KEY, JSON.stringify({
        activeId,
        threads: threads.slice(0, MAX_THREADS).map((t) => ({
          ...t, messages: t.messages.filter((m) => !m.streaming).slice(-MAX_MSGS),
        })),
      }));
    } catch { /* quota — not worth failing the UI over */ }
  }, [threads, activeId]);

  const active = threads.find((t) => t.id === activeId) ?? null;
  const messages = active?.messages ?? [];

  // All mutations funnel through here so `updatedAt` and ordering stay honest.
  const patchThread = useCallback((id: string, fn: (m: ChatMsg[]) => ChatMsg[]) => {
    setThreads((prev) => prev.map((t) =>
      t.id === id ? { ...t, messages: fn(t.messages), updatedAt: Date.now() } : t));
  }, []);

  const patchLast = useCallback((id: string, fn: (m: ChatMsg) => ChatMsg) => {
    patchThread(id, (msgs) => {
      if (!msgs.length) return msgs;
      const next = [...msgs];
      next[next.length - 1] = fn(next[next.length - 1]);
      return next;
    });
  }, [patchThread]);

  const run = useCallback(async (threadId: string, question: string, history: ChatMsg[]) => {
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setBusy(true);
    setStatus({ stage: "start" });
    patchThread(threadId, (m) => [...m, { role: "assistant", content: "", streaming: true, steps: [] }]);

    try {
      const res = await fetch("/api/ai/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: ctrl.signal,
        body: JSON.stringify({
          q: question,
          history: history.map((m) => ({ role: m.role, content: m.content })),
        }),
      });
      if (!res.ok || !res.body) throw new Error(`stream unavailable (${res.status})`);

      for await (const { event, payload } of sseEvents(res, ctrl.signal)) {
        if (event === "status") {
          setStatus(payload);
          patchLast(threadId, (m) => ({ ...m, steps: [...(m.steps ?? []), payload] }));
        } else if (event === "delta") {
          patchLast(threadId, (m) => ({ ...m, content: m.content + (payload.text ?? "") }));
        } else if (event === "meta") {
          patchLast(threadId, (m) => ({ ...m, intent: payload.intent, cards: payload.cards, sources: payload.sources }));
        } else if (event === "error") {
          patchLast(threadId, (m) => ({ ...m, error: true, content: payload.message || "Analysis failed." }));
        }
      }
      patchLast(threadId, (m) => ({ ...m, streaming: false }));
    } catch (e: any) {
      if (e?.name === "AbortError") {
        // User pressed stop — keep whatever text already arrived.
        patchLast(threadId, (m) => ({ ...m, streaming: false, stopped: true }));
      } else {
        patchLast(threadId, (m) => ({
          ...m, streaming: false, error: true,
          content: m.content || "Couldn't reach the ARTHA API. Check that the api container is running.",
        }));
      }
    } finally {
      setBusy(false);
      setStatus(null);
      abortRef.current = null;
    }
  }, [patchThread, patchLast]);

  const send = useCallback((text: string) => {
    const q = text.trim();
    if (!q || busy) return;
    const existing = threads.find((t) => t.id === activeId);
    const id = existing?.id ?? newId();
    const history = (existing?.messages ?? []).filter((m) => !m.error);
    const msg: ChatMsg = { role: "user", content: q };

    if (existing) {
      patchThread(id, (m) => [...m, msg]);
    } else {
      setThreads((prev) => [{ id, title: titleFrom(q), updatedAt: Date.now(), messages: [msg] }, ...prev]);
      setActiveId(id);
    }
    queueMicrotask(() => run(id, q, history));
  }, [busy, activeId, threads, patchThread, run]);

  const stop = useCallback(() => abortRef.current?.abort(), []);

  // Drop the last answer and re-ask the question that produced it.
  const regenerate = useCallback(() => {
    if (busy || !activeId) return;
    const t = threads.find((x) => x.id === activeId);
    if (!t) return;
    const lastUserIdx = t.messages.map((m) => m.role).lastIndexOf("user");
    if (lastUserIdx < 0) return;
    const question = t.messages[lastUserIdx].content;
    patchThread(activeId, (m) => m.slice(0, lastUserIdx + 1));
    queueMicrotask(() => run(activeId, question, t.messages.slice(0, lastUserIdx)));
  }, [busy, activeId, threads, patchThread, run]);

  // Edit a past question: everything after it is invalidated, so drop it and
  // re-run from that point rather than leaving replies to a question that no
  // longer exists sitting underneath.
  const editMessage = useCallback((index: number, text: string) => {
    const q = text.trim();
    if (!q || busy || !activeId) return;
    const t = threads.find((x) => x.id === activeId);
    if (!t || t.messages[index]?.role !== "user") return;
    const before = t.messages.slice(0, index);
    patchThread(activeId, () => [...before, { role: "user", content: q }]);
    queueMicrotask(() => run(activeId, q, before));
  }, [busy, activeId, threads, patchThread, run]);

  const newThread = useCallback(() => {
    abortRef.current?.abort();
    setActiveId(null);
  }, []);

  const selectThread = useCallback((id: string) => {
    abortRef.current?.abort();
    setActiveId(id);
  }, []);

  const deleteThread = useCallback((id: string) => {
    if (id === activeId) abortRef.current?.abort();
    setThreads((prev) => {
      const next = prev.filter((t) => t.id !== id);
      if (id === activeId) setActiveId(next[0]?.id ?? null);
      return next;
    });
  }, [activeId]);

  const renameThread = useCallback((id: string, title: string) => {
    const clean = title.trim();
    if (!clean) return;
    setThreads((prev) => prev.map((t) => (t.id === id ? { ...t, title: clean } : t)));
  }, []);

  return {
    threads, activeId, messages, busy, status,
    send, stop, regenerate, editMessage,
    newThread, selectThread, deleteThread, renameThread,
  };
}
