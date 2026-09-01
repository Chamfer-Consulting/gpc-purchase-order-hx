import {
  IconArchive,
  IconArrowsShuffle,
  IconLayoutDashboard,
  IconLeaf,
  IconRoute,
  IconSettings,
  IconShieldCheck,
  IconTable,
  IconTag,
  IconUsers,
  type IconProps,
} from "@tabler/icons-react";
import type { ComponentType } from "react";

export interface NavItem {
  label: string;
  to: string;
  icon: ComponentType<IconProps>;
  /** one-line page description, reused as the PageLayout subtitle */
  description: string;
}

export interface NavSection {
  label: string;
  items: NavItem[];
}

export const NAV_SECTIONS: NavSection[] = [
  {
    label: "Analyse",
    items: [
      {
        label: "Overview",
        to: "/",
        icon: IconLayoutDashboard,
        description: "Revenue and order health across the selected scope.",
      },
      {
        label: "Customers",
        to: "/customers",
        icon: IconUsers,
        description: "Revenue, orders, average order value and recency per customer.",
      },
      {
        label: "Products & Sizes",
        to: "/products",
        icon: IconLeaf,
        description: "Volume and revenue by product and container size.",
      },
      {
        label: "Explore",
        to: "/explore",
        icon: IconTable,
        description: "Pivot revenue, orders and quantity by any dimension and grain.",
      },
      {
        label: "Order Lifecycle",
        to: "/lifecycle",
        icon: IconRoute,
        description: "Lost sales from requested (PO) to shipped (invoice) — trended, by customer and product.",
      },
    ],
  },
  {
    label: "Operate",
    items: [
      {
        label: "Reconcile",
        to: "/reconcile",
        icon: IconArrowsShuffle,
        description:
          "Walk each order through extraction correctness, lifecycle status and its QuickBooks invoice match.",
      },
      {
        label: "Data Quality",
        to: "/data-quality",
        icon: IconShieldCheck,
        description: "Extraction errors, math checks and price anomalies to clear.",
      },
      {
        label: "Pricing",
        to: "/pricing",
        icon: IconTag,
        description: "Reference prices per customer and product, with price history.",
      },
    ],
  },
  {
    label: "Admin",
    items: [
      {
        label: "Archive",
        to: "/archive",
        icon: IconArchive,
        description: "Cancelled, withdrawn, voided and deleted orders — hidden from reports.",
      },
      {
        label: "Settings",
        to: "/settings",
        icon: IconSettings,
        description: "Connections, product and customer visibility, saved views.",
      },
    ],
  },
];

const ALL_ITEMS = NAV_SECTIONS.flatMap((s) => s.items.map((i) => ({ ...i, section: s.label })));

export interface PageMeta {
  title: string;
  description: string;
  breadcrumbs: { label: string; to?: string }[];
}

/** Look up nav-derived page metadata for a route (exact match). */
export function pageMeta(pathname: string): PageMeta | undefined {
  const hit = ALL_ITEMS.find((i) => i.to === pathname);
  if (!hit) return undefined;
  return {
    title: hit.label,
    description: hit.description,
    breadcrumbs: [{ label: hit.section }, { label: hit.label }],
  };
}
