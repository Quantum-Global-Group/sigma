import Link from "next/link";

export function ClerkUnavailable({ mode }: { mode: "sign-in" | "sign-up" }) {
  const label = mode === "sign-in" ? "Sign in" : "Sign up";

  return (
    <div className="w-full max-w-md rounded-xl border border-white/10 bg-white/5 p-8 text-center text-white">
      <h1 className="text-xl font-semibold mb-3">{label} unavailable</h1>
      <p className="text-sm text-gray-400 mb-6">
        Clerk is not configured. Add{" "}
        <code className="text-green-400">NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY</code> and{" "}
        <code className="text-green-400">CLERK_SECRET_KEY</code> to{" "}
        <code className="text-green-400">apps/web/.env.local</code>, or continue in dev mode.
      </p>
      <Link
        href="/dashboard"
        className="inline-block rounded-lg bg-green-500 px-4 py-2 text-sm font-medium text-gray-950 hover:bg-green-400"
      >
        Open dashboard (dev mode)
      </Link>
    </div>
  );
}
