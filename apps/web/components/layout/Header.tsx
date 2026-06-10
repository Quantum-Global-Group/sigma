import { UserButton } from "@clerk/nextjs";

import { isClerkConfigured } from "@/lib/auth-config";

export function Header() {
  return (
    <header className="h-14 border-b border-gray-200 bg-white flex items-center justify-between px-6 shrink-0">
      <span className="text-sm text-gray-500">Dashboard</span>
      {isClerkConfigured() ? (
        <UserButton afterSignOutUrl="/" />
      ) : (
        <span className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
          Dev mode (Clerk disabled)
        </span>
      )}
    </header>
  );
}
