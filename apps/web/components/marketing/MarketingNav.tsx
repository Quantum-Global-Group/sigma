import Link from "next/link";

export function MarketingNav() {
  return (
    <nav className="flex items-center justify-between px-8 py-6 border-b border-white/10">
      <Link href="/" className="text-xl font-bold tracking-tight">
        SIGMA
      </Link>
      <div className="flex items-center gap-6 text-sm">
        <Link href="/pricing" className="text-gray-400 hover:text-white transition-colors">
          Pricing
        </Link>
        <Link href="/docs" className="text-gray-400 hover:text-white transition-colors">
          Docs
        </Link>
        <Link
          href="/sign-in"
          className="px-4 py-2 rounded-md bg-white/10 hover:bg-white/20 transition-colors"
        >
          Sign in
        </Link>
        <Link
          href="/sign-up"
          className="px-4 py-2 rounded-md bg-indigo-600 hover:bg-indigo-500 transition-colors font-medium"
        >
          Get started
        </Link>
      </div>
    </nav>
  );
}
