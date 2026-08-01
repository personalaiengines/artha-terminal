"use client";
import { createContext, useContext, useState, ReactNode, useCallback, useEffect } from "react";
import type { ChangeMode } from "@/lib/format";

// ponytail: React context instead of Zustand. Only a few slices of global UI
// state (sidebar collapse, command palette, change-display mode). Add Zustand
// when state grows real slices (live quotes) that need selectors.
type UIState = {
  collapsed: boolean;
  toggleCollapsed: () => void;
  cmdkOpen: boolean;
  setCmdk: (v: boolean) => void;
  changeMode: ChangeMode;
  setChangeMode: (m: ChangeMode) => void;
};

const Ctx = createContext<UIState | null>(null);
const CHANGE_MODE_KEY = "artha:changeMode";

export function UIProvider({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [cmdkOpen, setCmdk] = useState(false);
  const [changeMode, setChangeModeState] = useState<ChangeMode>("pct");

  // Persisted across sessions — read once on mount (localStorage isn't
  // available during SSR, so this can't be the initial useState value).
  useEffect(() => {
    const saved = localStorage.getItem(CHANGE_MODE_KEY);
    if (saved === "pct" || saved === "abs") setChangeModeState(saved);
  }, []);

  const toggleCollapsed = useCallback(() => setCollapsed((v) => !v), []);
  const setChangeMode = useCallback((m: ChangeMode) => {
    setChangeModeState(m);
    try { localStorage.setItem(CHANGE_MODE_KEY, m); } catch {}
  }, []);

  return (
    <Ctx.Provider value={{ collapsed, toggleCollapsed, cmdkOpen, setCmdk, changeMode, setChangeMode }}>
      {children}
    </Ctx.Provider>
  );
}

export function useUI() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useUI must be used within UIProvider");
  return ctx;
}
