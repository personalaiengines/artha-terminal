"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Settings, LogOut } from "lucide-react";

/**
 * The avatar in the topbar, turned into an account menu. Was a bare Link to
 * /settings before this — clicking the avatar now shows who is signed in and
 * offers Settings + a real sign-out, rather than sign-out only existing as a
 * button buried inside the Settings page.
 */
export function AccountMenu() {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    fetch("/api/auth/me", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setEmail(d?.user?.email ?? null))
      .catch(() => {});
  }, [open]);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  async function signOut() {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label="Account"
        aria-expanded={open}
        className="h-8 w-8 rounded-full bg-gradient-to-br from-accent to-ai ring-focus transition-transform hover:scale-105"
      />
      {open && (
        <div className="absolute right-0 top-[calc(100%+8px)] z-40 w-56 overflow-hidden rounded-[var(--radius-md)] bg-elevated py-1.5 hairline shadow-[var(--shadow-lg)]">
          <div className="border-b border-line px-3.5 py-2.5">
            <div className="text-[10.5px] uppercase tracking-[0.08em] text-faint">Signed in as</div>
            <div className="mt-0.5 truncate text-[13px] font-medium text-frost">{email ?? "…"}</div>
          </div>
          <Link
            href="/settings"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2.5 px-3.5 py-2.5 text-[13px] text-mist hover:bg-raised hover:text-frost"
          >
            <Settings size={14} />
            Settings
          </Link>
          <button
            onClick={signOut}
            className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-[13px] text-mist hover:bg-down/10 hover:text-down"
          >
            <LogOut size={14} />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
