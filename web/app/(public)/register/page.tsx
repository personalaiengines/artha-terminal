"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Check, AlertCircle, Loader2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AlreadySignedIn } from "@/components/auth/already-signed-in";

/**
 * Registration as a guided connect flow rather than a wall of inputs.
 *
 * The one rule that shapes it: a key is TESTED against its real provider before
 * it is stored. A typo fails on the screen where it was made, not three screens
 * later when a panel is mysteriously empty.
 *
 * Stages 3 and 4 are skippable and say what skipping costs — the app already
 * degrades honestly without them, and a signup that pretends every field is
 * mandatory teaches the user the opposite.
 */

type Verdict = { state: "idle" | "busy" | "ok" | "bad"; msg?: string };

const STEPS = [
  { n: 1, title: "Create account", sub: "Email and password" },
  { n: 2, title: "Connect your broker", sub: "Live market data and your book" },
  { n: 3, title: "Enable the analyst", sub: "Any one free provider" },
  { n: 4, title: "Enrichment", sub: "News and search · optional" },
];

const BROKERS = [
  { id: "upstox", name: "Upstox", live: true },
  { id: "zerodha", name: "Zerodha", live: false },
  { id: "angelone", name: "Angel One", live: false },
  { id: "fyers", name: "Fyers", live: false },
  { id: "dhan", name: "Dhan", live: false },
  { id: "5paisa", name: "5paisa", live: false },
];

const PROVIDERS = [
  { id: "groq", name: "Groq", note: "Fastest", env: "GROQ_API_KEY" },
  { id: "google", name: "Gemini", note: "Own quota", env: "GOOGLE_API_KEY" },
  { id: "openrouter", name: "OpenRouter", note: "Free tier", env: "OPENROUTER_API_KEY" },
  { id: "nvidia", name: "NVIDIA", note: "Free NIM", env: "NVIDIA_API_KEY" },
];

const ENRICHMENT = [
  { id: "finnhub", env: "FINNHUB_API_KEY", name: "Finnhub", desc: "Company news · instant free key" },
  { id: "serpapi", env: "SERPAPI_KEY", name: "SerpAPI", desc: "Web search for the analyst · 250 free/month" },
  { id: "jina", env: "JINA_API_KEY", name: "Jina", desc: "Cleaner article extraction" },
];

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block font-mono text-[10.5px] uppercase tracking-[0.1em] text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-[12px] text-muted">{hint}</span>}
    </label>
  );
}

const inputCls =
  "h-11 w-full rounded-[var(--radius-sm)] bg-void px-3.5 text-[14px] text-frost outline-none hairline focus:border-accent/55 placeholder:text-faint";

function VerdictLine({ v }: { v: Verdict }) {
  if (v.state === "idle") return null;
  const tone = v.state === "ok" ? "text-up" : v.state === "bad" ? "text-down" : "text-muted";
  return (
    <div className={`mt-2 flex items-center gap-2 font-mono text-[11.5px] ${tone}`}>
      {v.state === "busy" && <Loader2 size={12} className="animate-spin" />}
      {v.state === "ok" && <Check size={12} />}
      {v.state === "bad" && <AlertCircle size={12} />}
      <span>{v.msg}</span>
    </div>
  );
}

export default function RegisterPage() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");

  const [keys, setKeys] = useState<Record<string, string>>({});
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>({});
  const [provider, setProvider] = useState("groq");

  const setKey = (k: string, v: string) => setKeys((s) => ({ ...s, [k]: v }));
  const setV = (k: string, v: Verdict) => setVerdicts((s) => ({ ...s, [k]: v }));

  /** Ask the server to call the provider with this key, before we store it. */
  async function testKey(envName: string) {
    const value = (keys[envName] ?? "").trim();
    if (!value) return setV(envName, { state: "bad", msg: "Enter a key first" });
    setV(envName, { state: "busy", msg: "Calling the provider…" });
    try {
      const res = await fetch("/api/auth/test-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: envName, key: value }),
      });
      const b = await res.json().catch(() => null);
      if (b?.ok) setV(envName, { state: "ok", msg: b.detail ?? "Verified" });
      else setV(envName, { state: "bad", msg: b?.error ?? "Key rejected by the provider" });
    } catch {
      setV(envName, { state: "bad", msg: "Could not reach the terminal" });
    }
  }

  function validateAccount(): string | null {
    if (!email.includes("@")) return "Enter a valid email address.";
    if (pw.length < 12) return "Password must be at least 12 characters.";
    if (pw !== pw2) return "Passwords do not match.";
    return null;
  }

  async function finish() {
    setErr(null);
    setBusy(true);
    try {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password: pw,
          keys: Object.fromEntries(Object.entries(keys).filter(([, v]) => v.trim())),
        }),
      });
      const b = await res.json().catch(() => null);
      if (!res.ok || !b?.ok) {
        setErr(b?.error ?? "Could not create the account.");
        setStep(1);
        return;
      }
      setStep(5);
    } catch {
      setErr("Could not reach the server. Is the terminal running?");
      setStep(1);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-abyss px-6 py-10">
      <div className="mx-auto max-w-[1080px]">
        <AlreadySignedIn />
        <div className="grid overflow-hidden rounded-[var(--radius-xl)] hairline shadow-[var(--shadow-lg)] lg:grid-cols-2">
          {/* rail */}
          <aside className="flex flex-col border-b border-line bg-void p-9 lg:border-b-0 lg:border-r">
            <Link href="/" className="flex items-center gap-2.5">
              <div className="grid h-7 w-7 place-items-center rounded-[var(--radius-xs)] bg-gradient-to-br from-accent to-ai font-mono text-[13px] font-bold text-white">
                A
              </div>
              <b className="text-[15px] font-[640] tracking-[-0.01em]">ARTHA</b>
            </Link>

            <div className="mt-10 flex flex-col gap-0.5">
              {STEPS.map((s) => {
                const done = step > s.n;
                const now = step === s.n;
                return (
                  <div
                    key={s.n}
                    className={`flex gap-3.5 rounded-[var(--radius-sm)] px-3 py-3 ${now ? "bg-elevated" : ""}`}
                  >
                    <span
                      className={`grid h-6 w-6 shrink-0 place-items-center rounded-full font-mono text-[11.5px] font-[600] ${
                        done
                          ? "border border-up/35 bg-up-soft text-up"
                          : now
                            ? "border border-accent bg-accent text-white"
                            : "border border-line bg-elevated text-faint"
                      }`}
                    >
                      {done ? <Check size={12} /> : s.n}
                    </span>
                    <div>
                      <div className={`text-[13.5px] ${now ? "font-[590] text-frost" : done ? "text-mist" : "text-faint"}`}>
                        {s.title}
                      </div>
                      <div className={`mt-0.5 text-[12px] ${now ? "text-muted" : "text-faint/75"}`}>{s.sub}</div>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="mt-auto flex items-start gap-2.5 pt-8 text-[12px] leading-relaxed text-faint">
              <ShieldCheck size={14} className="mt-px shrink-0" />
              <span>
                <b className="font-[560] text-muted">Your keys never leave your machine.</b> Encrypted at
                rest, decrypted only to call the provider, and never sent back to your browser once saved.
              </span>
            </div>
          </aside>

          {/* pane */}
          <main className="bg-surface p-9">
            {err && (
              <div
                role="alert"
                className="mb-5 flex items-start gap-2.5 rounded-[var(--radius-sm)] border border-down/30 bg-down/10 px-3 py-2.5 text-[12.5px] text-down"
              >
                <AlertCircle size={14} className="mt-px shrink-0" />
                <span>{err}</span>
              </div>
            )}

            {step === 1 && (
              <>
                <h1 className="text-[23px] font-[620] tracking-[-0.02em]">Create your account</h1>
                <p className="mb-6 mt-1.5 max-w-[48ch] text-[13.5px] text-muted">
                  Your watchlists, alerts and P&amp;L stay yours. Market data is shared across
                  everyone on this terminal; your book is not.
                </p>
                <div className="flex flex-col gap-4">
                  <Field label="Email">
                    <input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" className={inputCls} />
                  </Field>
                  <Field label="Password" hint="At least 12 characters.">
                    <input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder="••••••••••••" className={inputCls} />
                  </Field>
                  <Field label="Confirm password">
                    <input type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} placeholder="Type it again" className={inputCls} />
                  </Field>
                </div>
                <div className="mt-7 flex items-center gap-3 border-t border-line pt-5">
                  <Button
                    variant="primary"
                    size="lg"
                    onClick={() => {
                      const v = validateAccount();
                      if (v) return setErr(v);
                      setErr(null);
                      setStep(2);
                    }}
                  >
                    Continue
                  </Button>
                  <span className="text-[12.5px] text-muted">
                    Already have one?{" "}
                    <Link href="/login" className="text-accent hover:underline">Sign in</Link>
                  </span>
                </div>
              </>
            )}

            {step === 2 && (
              <>
                <h1 className="text-[23px] font-[620] tracking-[-0.02em]">Connect your broker</h1>
                <p className="mb-5 mt-1.5 max-w-[48ch] text-[13.5px] text-muted">
                  Upstox is live today. The others are on the roadmap.
                </p>
                <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
                  {BROKERS.map((b) => (
                    <button
                      key={b.id}
                      disabled={!b.live}
                      aria-pressed={b.live}
                      className={`rounded-[var(--radius-md)] p-4 text-left transition-all ${
                        b.live
                          ? "border border-accent bg-elevated shadow-[0_0_0_1px_var(--color-accent)]"
                          : "cursor-not-allowed border border-line bg-elevated opacity-50"
                      }`}
                    >
                      <div className="mb-2 text-[13.5px] font-[600]">{b.name}</div>
                      <span className={`font-mono text-[9.5px] uppercase tracking-[0.09em] ${b.live ? "text-up" : "text-faint"}`}>
                        {b.live ? "● Live" : "Coming soon"}
                      </span>
                    </button>
                  ))}
                </div>
                <p className="mt-4 rounded-[var(--radius-sm)] border border-dashed border-line bg-void px-3.5 py-3 text-[12px] text-muted">
                  Adding a broker means mapping its quote, chain and holdings APIs onto ARTHA&rsquo;s
                  existing shape. Upstox is done. The rest arrive one at a time.
                </p>

                <div className="mt-6 flex flex-col gap-4">
                  <Field
                    label="Analytics token · drives market data"
                    hint="Valid ~1 year. Without it the terminal falls back to Yahoo, roughly 15 minutes delayed."
                  >
                    <div className="flex gap-2.5">
                      <input
                        value={keys.UPSTOX_ANALYTICS_TOKEN ?? ""}
                        onChange={(e) => setKey("UPSTOX_ANALYTICS_TOKEN", e.target.value)}
                        placeholder="eyJ0eXAiOiJKV1QiLCJhbGci…"
                        className={`${inputCls} font-mono text-[12.5px]`}
                      />
                      <button
                        onClick={() => testKey("UPSTOX_ANALYTICS_TOKEN")}
                        className="shrink-0 rounded-[var(--radius-sm)] bg-elevated px-4 text-[12.5px] font-[590] text-mist hairline hover:bg-raised hover:text-frost"
                      >
                        Test
                      </button>
                    </div>
                    <VerdictLine v={verdicts.UPSTOX_ANALYTICS_TOKEN ?? { state: "idle" }} />
                  </Field>

                  <Field label="Client ID and secret · for the daily OAuth token" hint="Needed for holdings, positions and P&L. Market data works without it.">
                    <div className="flex gap-2.5">
                      <input value={keys.UPSTOX_CLIENT_ID ?? ""} onChange={(e) => setKey("UPSTOX_CLIENT_ID", e.target.value)} placeholder="Client ID" className={`${inputCls} font-mono text-[12.5px]`} />
                      <input value={keys.UPSTOX_CLIENT_SECRET ?? ""} onChange={(e) => setKey("UPSTOX_CLIENT_SECRET", e.target.value)} placeholder="Client secret" className={`${inputCls} font-mono text-[12.5px]`} />
                    </div>
                  </Field>
                </div>

                <div className="mt-7 flex items-center gap-3 border-t border-line pt-5">
                  <Button variant="secondary" size="lg" onClick={() => setStep(1)}>Back</Button>
                  <Button variant="primary" size="lg" onClick={() => setStep(3)}>Continue</Button>
                </div>
              </>
            )}

            {step === 3 && (
              <>
                <h1 className="text-[23px] font-[620] tracking-[-0.02em]">Enable the analyst</h1>
                <p className="mb-5 mt-1.5 max-w-[48ch] text-[13.5px] text-muted">
                  One free key is enough. The router walks providers in order and falls through on
                  rate limits, so a second is insurance rather than a requirement.
                </p>
                <div className="mb-5 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {PROVIDERS.map((p) => (
                    <button
                      key={p.id}
                      aria-pressed={provider === p.id}
                      onClick={() => setProvider(p.id)}
                      className={`rounded-[var(--radius-sm)] px-2 py-2.5 text-center text-[11.5px] font-[560] transition-all ${
                        provider === p.id
                          ? "border border-ai/45 bg-ai-soft text-[#cdbdf5]"
                          : "border border-line bg-elevated text-muted hover:text-frost"
                      }`}
                    >
                      {p.name}
                      <small className="mt-0.5 block font-mono text-[9px] tracking-[0.06em] opacity-65">{p.note}</small>
                    </button>
                  ))}
                </div>

                {PROVIDERS.filter((p) => p.id === provider).map((p) => (
                  <Field key={p.id} label={`${p.name} API key`} hint="We call the provider now, with this key, before saving it.">
                    <div className="flex gap-2.5">
                      <input
                        value={keys[p.env] ?? ""}
                        onChange={(e) => setKey(p.env, e.target.value)}
                        placeholder="Paste your key"
                        className={`${inputCls} font-mono text-[12.5px]`}
                      />
                      <button
                        onClick={() => testKey(p.env)}
                        className="shrink-0 rounded-[var(--radius-sm)] bg-elevated px-4 text-[12.5px] font-[590] text-mist hairline hover:bg-raised hover:text-frost"
                      >
                        Test key
                      </button>
                    </div>
                    <VerdictLine v={verdicts[p.env] ?? { state: "idle" }} />
                  </Field>
                ))}

                <div className="mt-7 flex items-center gap-3 border-t border-line pt-5">
                  <Button variant="secondary" size="lg" onClick={() => setStep(2)}>Back</Button>
                  <Button variant="primary" size="lg" onClick={() => setStep(4)}>Continue</Button>
                  <button onClick={() => setStep(4)} className="ml-auto text-[12.5px] text-muted underline underline-offset-[3px] hover:text-mist">
                    Skip — the analyst page will say it&rsquo;s unconfigured
                  </button>
                </div>
              </>
            )}

            {step === 4 && (
              <>
                <h1 className="text-[23px] font-[620] tracking-[-0.02em]">Enrichment</h1>
                <p className="mb-5 mt-1.5 max-w-[48ch] text-[13.5px] text-muted">
                  All optional. Each one thins out a panel rather than breaking it, and the app tells
                  you which fallback it used.
                </p>
                <div className="flex flex-col gap-3">
                  {ENRICHMENT.map((o) => (
                    <div key={o.id} className="rounded-[var(--radius-sm)] bg-elevated p-3.5 hairline">
                      <div className="mb-2 flex items-center gap-3">
                        <div className="flex-1">
                          <div className="text-[13px] font-[560]">{o.name}</div>
                          <div className="mt-0.5 text-[11.5px] text-muted">{o.desc}</div>
                        </div>
                        <span className="rounded border border-line px-1.5 py-0.5 font-mono text-[9.5px] uppercase tracking-[0.08em] text-faint">
                          Optional
                        </span>
                      </div>
                      <input
                        value={keys[o.env] ?? ""}
                        onChange={(e) => setKey(o.env, e.target.value)}
                        placeholder="Paste key, or leave blank"
                        className={`${inputCls} font-mono text-[12.5px]`}
                      />
                    </div>
                  ))}
                </div>
                <div className="mt-7 flex items-center gap-3 border-t border-line pt-5">
                  <Button variant="secondary" size="lg" onClick={() => setStep(3)}>Back</Button>
                  <Button variant="primary" size="lg" onClick={finish} disabled={busy}>
                    {busy ? "Creating…" : "Finish setup"}
                  </Button>
                  <button onClick={finish} disabled={busy} className="ml-auto text-[12.5px] text-muted underline underline-offset-[3px] hover:text-mist">
                    Skip all
                  </button>
                </div>
              </>
            )}

            {step === 5 && (
              <div className="py-10 text-center">
                <div className="mx-auto mb-6 grid h-14 w-14 place-items-center rounded-full border border-up/40 bg-up-soft">
                  <Check size={26} className="text-up" />
                </div>
                <h1 className="text-[23px] font-[620] tracking-[-0.02em]">Your terminal is ready</h1>
                <p className="mx-auto mt-2 max-w-[42ch] text-[13.5px] text-muted">
                  Every key you provided was tested against its provider before it was stored.
                </p>
                <div className="mt-6 flex flex-col gap-px overflow-hidden rounded-[var(--radius-md)] text-left hairline">
                  {[
                    ["Account", email],
                    ["Broker", keys.UPSTOX_ANALYTICS_TOKEN ? "Upstox · connected" : "Not connected"],
                    ["Analyst", Object.keys(keys).some((k) => PROVIDERS.some((p) => p.env === k && keys[k])) ? "Configured" : "Skipped"],
                    ["Stored as", "Encrypted · SQLite"],
                  ].map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between bg-elevated px-4 py-3 text-[12.5px]">
                      <span className="text-muted">{k}</span>
                      <span className="font-mono text-[11.5px] text-mist">{v}</span>
                    </div>
                  ))}
                </div>
                <Button
                  variant="primary"
                  size="lg"
                  className="mt-6 w-full justify-center"
                  onClick={() => { router.push("/dashboard"); router.refresh(); }}
                >
                  Open the terminal
                </Button>
              </div>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
