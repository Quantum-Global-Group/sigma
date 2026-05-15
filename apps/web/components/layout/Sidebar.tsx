"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Overview" },
  { href: "/signals", label: "Signals" },
  { href: "/positions", label: "Positions" },
  { href: "/orders", label: "Orders" },
  { href: "/execution", label: "Execution" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/api-keys", label: "API Keys" },
  { href: "/billing", label: "Billing" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 shrink-0 border-r border-gray-200 min-h-screen bg-white pt-6">
      <div className="px-4 mb-6">
        <span className="text-lg font-bold tracking-tight text-gray-900">SIGMA</span>
      </div>
      <nav className="flex flex-col gap-1 px-2">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "px-3 py-2 rounded-md text-sm font-medium transition-colors",
              pathname === item.href
                ? "bg-indigo-50 text-indigo-700"
                : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
            )}
          >
            {item.label}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
