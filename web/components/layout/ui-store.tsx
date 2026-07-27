"use client";
import { createContext, useContext, useState, ReactNode, useCallback } from "react";

// ponytail: React context instead of Zustand. Only two booleans of global UI
// state (sidebar collapse, command palette). Add Zustand when state grows real
// slices (live quotes, user prefs) that need selectors/persistence.
type UIState = {
  collapsed: boolean;
  toggleCollapsed: () => void;
  cmdkOpen: boolean;
  setCmdk: (v: boolean) => void;
};

const Ctx = createContext<UIState | null>(null);

export function UIProvider({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [cmdkOpen, setCmdk] = useState(false);
  const toggleCollapsed = useCallback(() => setCollapsed((v) => !v), []);
  return (
    <Ctx.Provider value={{ collapsed, toggleCollapsed, cmdkOpen, setCmdk }}>
      {children}
    </Ctx.Provider>
  );
}

export function useUI() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useUI must be used within UIProvider");
  return ctx;
}
