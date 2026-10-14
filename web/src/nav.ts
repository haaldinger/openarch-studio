import {
  LayoutGrid,
  Search,
  MessagesSquare,
  FileStack,
  Activity,
  Layers,
  Share2,
  HelpCircle,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
  /** Short line shown under the label in the rail. */
  hint: string;
}

/** Single source of truth for the authenticated shell's navigation and routes. */
export const NAV_ITEMS: NavItem[] = [
  { path: "/library", label: "Library", icon: LayoutGrid, hint: "Upload & browse" },
  { path: "/search", label: "Search", icon: Search, hint: "Keyword & semantic" },
  { path: "/ask", label: "Ask", icon: MessagesSquare, hint: "Grounded answers" },
  { path: "/graph", label: "Graph", icon: Share2, hint: "Entities & relations" },
  { path: "/documents", label: "Documents", icon: FileStack, hint: "Inspect records" },
  { path: "/activity", label: "Activity", icon: Activity, hint: "Enrichment jobs" },
  { path: "/capabilities", label: "Capabilities", icon: Layers, hint: "Native vs added" },
  { path: "/help", label: "Help", icon: HelpCircle, hint: "How Studio works" },
];
