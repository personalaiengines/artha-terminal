"use client";
import { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { motion } from "framer-motion";
import { UIProvider } from "./ui-store";
import { Sidebar } from "./sidebar";
import { Topbar } from "./topbar";
import { CommandPalette } from "./command-palette";
import { SystemBanner } from "./system-banner";

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <UIProvider>
      <div className="flex min-h-screen">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar />
          <SystemBanner />
          <main className="flex-1 px-4 py-6 md:px-8 md:py-8 scrollbar-slim">
            {/* Keyed entrance only — no AnimatePresence/exit. In the App Router
                `children` swaps immediately on nav, so mode="wait" left a blank
                gap during the outgoing exit. Remounting on pathname fades the
                new page in cleanly with nothing to wait on. */}
            <motion.div
              key={pathname}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
              className="mx-auto max-w-[1440px]"
            >
              {children}
            </motion.div>
          </main>
        </div>
      </div>
      <CommandPalette />
    </UIProvider>
  );
}
