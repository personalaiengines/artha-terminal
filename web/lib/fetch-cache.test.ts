import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getOnce } from "./fetch-cache";

// The cache is module state and there is no reset hook (nothing but a test would
// want one), so every case uses its own URL.
const calls: string[] = [];

const stub = (reply: (url: string) => Promise<unknown>) => {
  (globalThis as { fetch?: unknown }).fetch = (url: string) => {
    calls.push(url);
    return reply(url);
  };
};
const json = (value: unknown) => Promise.resolve({ json: () => Promise.resolve(value) });

beforeEach(() => {
  calls.length = 0;
  vi.useFakeTimers();
  stub(() => json({ s: "ok" }));
});
afterEach(() => { vi.useRealTimers(); });

describe("getOnce", () => {
  it("serves two concurrent callers from one request", async () => {
    const [a, b] = await Promise.all([getOnce("/a", 55_000), getOnce("/a", 55_000)]);
    expect(calls).toEqual(["/a"]);
    expect(a).toEqual({ s: "ok" });
    expect(b).toEqual({ s: "ok" });
  });

  it("serves a later caller inside the TTL, and refetches past it", async () => {
    await getOnce("/b", 55_000);
    vi.advanceTimersByTime(54_000);
    await getOnce("/b", 55_000);
    expect(calls).toEqual(["/b"]);
    vi.advanceTimersByTime(2_000);
    await getOnce("/b", 55_000);
    expect(calls).toEqual(["/b", "/b"]);
  });

  it("keys on the whole URL — another resolution is another request", async () => {
    await Promise.all([getOnce("/c?resolution=15", 55_000), getOnce("/c?resolution=60", 55_000)]);
    expect(calls).toEqual(["/c?resolution=15", "/c?resolution=60"]);
  });

  it("does not cache a failure — a cached one would freeze the pane for a minute", async () => {
    stub(() => Promise.reject(new Error("network down")));
    await expect(getOnce("/d", 55_000)).rejects.toThrow("network down");
    stub(() => json({ s: "ok" }));
    await expect(getOnce("/d", 55_000)).resolves.toEqual({ s: "ok" });
    expect(calls).toEqual(["/d", "/d"]);
  });
});
