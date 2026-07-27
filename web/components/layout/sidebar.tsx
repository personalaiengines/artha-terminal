"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "framer-motion";
import { PanelLeftClose, PanelLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import { NAV, NAV_GROUPS } from "@/lib/nav";
import { useUI } from "./ui-store";

export function Sidebar() {
  const pathname = usePathname();
  const { collapsed, toggleCollapsed } = useUI();

  const isActive = (href: string) => href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <motion.aside
      animate={{ width: collapsed ? 68 : 244 }}
      transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
      className="sticky top-0 z-40 hidden h-screen shrink-0 flex-col border-r border-line bg-void/80 backdrop-blur-xl md:flex"
    >
      {/* Brand */}
      <div className="flex h-14 items-center gap-2.5 px-4">
        <div className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] bg-gradient-to-br from-accent to-ai shadow-[0_4px_14px_-2px_rgba(59,130,246,0.6)]">
          <span className="text-[15px] font-black text-white">A</span>
        </div>
        {!collapsed && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="min-w-0">
            <div className="text-[14px] font-bold tracking-tight text-frost leading-none">ARTHA</div>
            <div className="text-[9.5px] font-medium uppercase tracking-[0.18em] text-muted mt-1">Terminal</div>
          </motion.div>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto scrollbar-slim px-3 py-2">
        {NAV_GROUPS.map((group) => {
          const items = NAV.filter((n) => n.group === group);
          return (
            <div key={group} className="mb-4">
              {!collapsed && (
                <div className="px-2.5 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-faint">{group}</div>
              )}
              <div className="flex flex-col gap-0.5">
                {items.map((item) => {
                  const active = isActive(item.href);
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      title={collapsed ? item.label : undefined}
                      className={cn(
                        "group relative flex items-center gap-2.5 rounded-[var(--radius-sm)] px-2.5 py-2 text-[13px] font-medium transition-colors ring-focus",
                        active ? "text-frost" : "text-muted hover:text-frost hover:bg-raised/60",
                        collapsed && "justify-center"
                      )}
                    >
                      {active && (
                        <motion.span layoutId="nav-active" className="absolute inset-0 rounded-[var(--radius-sm)] bg-raised hairline" transition={{ type: "spring", stiffness: 400, damping: 34 }} />
                      )}
                      <item.icon size={17} strokeWidth={2} className={cn("relative z-10 shrink-0", active && "text-accent")} />
                      {!collapsed && <span className="relative z-10 truncate">{item.label}</span>}
                      {!collapsed && item.badge && (
                        <span className="relative z-10 ml-auto rounded-full bg-ai-soft px-1.5 py-0.5 text-[9px] font-bold uppercase text-ai">{item.badge}</span>
                      )}
                    </Link>
                  );
                })}
              </div>
            </div>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="border-t border-line p-3">
        <button
          onClick={toggleCollapsed}
          className="flex w-full items-center gap-2.5 rounded-[var(--radius-sm)] px-2.5 py-2 text-[12px] font-medium text-muted hover:text-frost hover:bg-raised/60 transition-colors"
        >
          {collapsed ? <PanelLeft size={17} /> : <><PanelLeftClose size={17} /><span>Collapse</span></>}
        </button>
      </div>
    </motion.aside>
  );
}
