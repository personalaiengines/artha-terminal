import {
  LayoutDashboard, LineChart, Wallet, Star, Sparkles, FlaskConical,
  CandlestickChart, Layers, LayoutGrid, Newspaper, CalendarClock, Bell, ShieldAlert,
  Settings, type LucideIcon,
} from "lucide-react";

export type NavItem = { label: string; href: string; icon: LucideIcon; group: string; badge?: string };

export const NAV: NavItem[] = [
  { label: "Dashboard", href: "/", icon: LayoutDashboard, group: "Workspace" },
  { label: "Markets", href: "/markets", icon: LineChart, group: "Workspace" },
  { label: "Portfolio", href: "/portfolio", icon: Wallet, group: "Workspace" },
  { label: "Watchlists", href: "/watchlists", icon: Star, group: "Workspace" },

  { label: "AI Analyst", href: "/ai-analyst", icon: Sparkles, group: "Intelligence", badge: "AI" },
  { label: "Research", href: "/research", icon: FlaskConical, group: "Intelligence" },
  { label: "News", href: "/news", icon: Newspaper, group: "Intelligence" },

  // LayoutGrid, because it reads as a grid and nothing else uses it: LineChart
  // is already Markets and F&O, CandlestickChart is Stocks.
  { label: "Charts", href: "/charts", icon: LayoutGrid, group: "Trading" },
  { label: "Stocks", href: "/stocks", icon: CandlestickChart, group: "Trading" },
  { label: "Options", href: "/options", icon: Layers, group: "Trading" },
  { label: "F&O", href: "/fno", icon: LineChart, group: "Trading" },

  { label: "Economic Calendar", href: "/calendar", icon: CalendarClock, group: "Monitor" },
  { label: "Alerts", href: "/alerts", icon: Bell, group: "Monitor" },
  { label: "Risk Analysis", href: "/risk", icon: ShieldAlert, group: "Monitor" },

  { label: "Settings", href: "/settings", icon: Settings, group: "System" },
];

export const NAV_GROUPS = ["Workspace", "Intelligence", "Trading", "Monitor", "System"];
