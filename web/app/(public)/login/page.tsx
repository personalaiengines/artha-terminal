"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { KeyRound, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AlreadySignedIn } from "@/components/auth/already-signed-in";

/**
 * `next` comes from the middleware redirect, and is read from the URL at submit
 * time rather than through `useSearchParams`.
 *
 * That hook forces the component into a Suspense boundary, which server-rendered
 * as an empty page — the form only appeared once JS hydrated. It is needed for
 * one string used once, so reading `window.location` in the submit handler costs
 * nothing and lets the whole page render on the server.
 *
 * Only a same-site PATH is ever followed. An absolute URL here would be an open
 * redirect, and "sign in and we'll take you to your dashboard" is exactly the
 * pretext that makes one work on a real person.
 */
function safeNext(): string {
  if (typeof window === "undefined") return "/dashboard";
  const raw = new URLSearchParams(window.location.search).get("next");
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return "/dashboard";
  return raw;
}

function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, remember }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok || !body?.ok) {
        // Deliberately one message for both "no such account" and "wrong
        // password". Telling them apart hands an attacker a list of who has an
        // account here.
        setErr(body?.error ?? "Email or password is incorrect.");
        return;
      }
      router.push(safeNext());
      router.refresh();
    } catch {
      setErr("Could not reach the server. Is the terminal running?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-[412px]">
      <Link href="/" className="mb-6 flex items-center justify-center gap-2.5">
        <div className="grid h-7 w-7 place-items-center rounded-[var(--radius-xs)] bg-gradient-to-br from-accent to-ai font-mono text-[13px] font-bold text-white">
          A
        </div>
        <b className="text-[15px] font-[640] tracking-[-0.01em]">ARTHA</b>
      </Link>

      <AlreadySignedIn />

      <div className="rounded-[var(--radius-lg)] bg-elevated p-8 hairline shadow-[var(--shadow-lg)]">
        <h1 className="text-center text-[23px] font-[620] tracking-[-0.02em]">Welcome back</h1>
        <p className="mb-6 mt-1.5 text-center text-[13.5px] text-muted">
          Sign in to your terminal.
        </p>

        {err && (
          <div
            role="alert"
            className="mb-4 flex items-start gap-2.5 rounded-[var(--radius-sm)] border border-down/30 bg-down/10 px-3 py-2.5 text-[12.5px] text-down"
          >
            <AlertCircle size={14} className="mt-px shrink-0" />
            <span>{err}</span>
          </div>
        )}

        <form onSubmit={submit} className="flex flex-col gap-4">
          <label>
            <span className="mb-1.5 block font-mono text-[10.5px] uppercase tracking-[0.1em] text-muted">
              Email
            </span>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="h-11 w-full rounded-[var(--radius-sm)] bg-void px-3.5 text-[14px] text-frost outline-none hairline focus:border-accent/55"
            />
          </label>

          <label>
            <span className="mb-1.5 block font-mono text-[10.5px] uppercase tracking-[0.1em] text-muted">
              Password
            </span>
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••••••"
              className="h-11 w-full rounded-[var(--radius-sm)] bg-void px-3.5 text-[14px] text-frost outline-none hairline focus:border-accent/55"
            />
          </label>

          <label className="flex cursor-pointer items-center gap-2.5 text-[13px] text-mist select-none">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              className="h-4 w-4 rounded-[4px] accent-[var(--color-accent)]"
            />
            Keep me signed in for 30 days
          </label>

          <Button type="submit" variant="primary" size="lg" className="mt-1 w-full justify-center" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>

        <div className="mt-6 flex items-start gap-2.5 rounded-[var(--radius-sm)] bg-void px-3.5 py-3 text-[11.5px] leading-relaxed text-muted hairline">
          <KeyRound size={13} className="mt-px shrink-0 text-accent" />
          <span>
            Sessions are revocable — signing out deletes the token on the server rather than
            waiting for it to expire. You can end every session from Settings.
          </span>
        </div>
      </div>

      <p className="mt-5 text-center text-[13px] text-muted">
        No account yet?{" "}
        <Link href="/register" className="text-accent hover:underline">
          Create your terminal
        </Link>
      </p>
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-abyss px-6 py-16">
      <LoginForm />
    </div>
  );
}
