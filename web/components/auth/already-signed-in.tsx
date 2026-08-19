"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { UserCheck } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Shown at the top of /login and /register when the visitor already holds a
 * live session. Replaces a silent middleware redirect that used to bounce
 * straight to /dashboard the instant either page loaded — which, from the
 * visitor's side, made "Create your terminal" appear to do nothing but log
 * them in. This makes the state visible and gives an actual choice instead
 * of deciding for them.
 */
export function AlreadySignedIn() {
  const [email, setEmail] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    fetch("/api/auth/me", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (live && d?.ok) setEmail(d.user?.email ?? null);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  if (!email) return null;

  async function signOut() {
    setBusy(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } finally {
      window.location.reload();
    }
  }

  return (
    <div className="mb-6 flex flex-wrap items-center gap-3 rounded-[var(--radius-sm)] border border-accent/30 bg-accent-soft px-4 py-3 text-[12.5px]">
      <UserCheck size={15} className="shrink-0 text-accent" />
      <span className="text-mist">
        Already signed in as <b className="font-[600] text-frost">{email}</b>.
      </span>
      <div className="ml-auto flex gap-2">
        <Link href="/dashboard">
          <Button variant="primary" size="sm">Go to dashboard</Button>
        </Link>
        <Button variant="ghost" size="sm" onClick={signOut} disabled={busy}>
          {busy ? "Signing out…" : "Sign out"}
        </Button>
      </div>
    </div>
  );
}
