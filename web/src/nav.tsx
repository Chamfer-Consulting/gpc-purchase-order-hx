import {
  IconArchive,
  IconArrowsShuffle,
  IconChartLine,
  IconHistory,
  IconLayoutDashboard,
  IconLeaf,
  IconFileImport,
  IconListDetails,
  IconPlant2,
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
  /** only render the sidebar link for admins (the route/API guard themselves too) */
  adminOnly?: boolean;
  /** an admin can grant this specific page to an "external viewer" account
   *  (Settings -> Team) — builds that checkbox list. Keep in sync with the
   *  backend's EXTERNAL_VIEWABLE_PAGES (backend/app/auth.py); every route
   *  behind one of these also has its own require_page(...) dependency. */
  externalViewable?: boolean;
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
        externalViewable: true,
      },
      {
        label: "Customers",
        to: "/customers",
        icon: IconUsers,
        description: "Revenue, orders, average order value and recency per customer.",
        externalViewable: true,
      },
      {
        label: "Products & Sizes",
        to: "/products",
        icon: IconLeaf,
        description: "Volume and revenue by product and container size.",
        externalViewable: true,
      },
      {
        label: "Explore",
        to: "/explore",
        icon: IconTable,
        description: "Pivot revenue, orders and quantity by any dimension and grain.",
        externalViewable: true,
      },
      {
        label: "Order Lifecycle",
        to: "/lifecycle",
        icon: IconRoute,
        description: "Lost sales from requested (PO) to shipped (invoice) — trended, by customer and product.",
        externalViewable: true,
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
        externalViewable: true,
      },
    ],
  },
  {
    label: "Product Yields",
    items: [
      {
        label: "Trends",
        to: "/yields",
        icon: IconChartLine,
        description: "Harvest weight and tray trends — weekly, monthly, quarterly, yearly.",
        externalViewable: true,
      },
      {
        label: "Entries",
        to: "/yields/entries",
        icon: IconListDetails,
        description:
          "Harvest log entries from the field kiosk — weight, trays, who and where. Admins can also log a " +
          "harvest or manage grower notes from here.",
        externalViewable: true,
      },
      {
        label: "Products",
        to: "/yields/admin",
        icon: IconPlant2,
        description: "Manage the kiosk's harvest product catalog and its sales-SKU links.",
      },
      {
        label: "Import",
        to: "/yields/import",
        icon: IconFileImport,
        description: "Bring in past harvest history from a CSV file.",
        adminOnly: true,
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
        label: "Audit history",
        to: "/audit",
        icon: IconHistory,
        description: "Every change on record — who, what, when, where and why.",
        adminOnly: true,
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

/** The pages an admin can grant to an external_viewer account — builds the
 *  checkbox list in Settings -> Team. See NavItem.externalViewable. */
export const EXTERNAL_VIEWABLE_PAGES = ALL_ITEMS.filter((i) => i.externalViewable).map((i) => ({
  to: i.to,
  label: i.label,
}));

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
