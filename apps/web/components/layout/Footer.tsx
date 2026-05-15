import Link from "next/link";

const GUMROAD_DASHBOARD = process.env.NEXT_PUBLIC_GUMROAD_DASHBOARD_URL;
const GUMROAD_ML = process.env.NEXT_PUBLIC_GUMROAD_ML_URL;

type LinkItem = { label: string; href: string; external?: boolean };

const COLUMNS: { heading: string; links: LinkItem[] }[] = [
  {
    heading: "Product",
    links: [
      { label: "Pricing", href: "/pricing" },
      { label: "Docs", href: "/docs" },
      { label: "Dashboard", href: "/dashboard" },
    ],
  },
  {
    heading: "Templates",
    links: [
      ...(GUMROAD_DASHBOARD
        ? [{ label: "Dashboard template", href: GUMROAD_DASHBOARD, external: true }]
        : []),
      ...(GUMROAD_ML
        ? [{ label: "ML boilerplate", href: GUMROAD_ML, external: true }]
        : []),
      ...(!GUMROAD_DASHBOARD && !GUMROAD_ML
        ? [{ label: "Coming soon", href: "#" }]
        : []),
    ],
  },
  {
    heading: "Company",
    links: [
      { label: "Sign in", href: "/sign-in" },
      { label: "Get started", href: "/sign-up" },
      { label: "Contact", href: "mailto:hello@sigma.dev", external: true },
    ],
  },
];

export function Footer() {
  return (
    <footer className="border-t border-white/10 mt-20">
      <div className="max-w-6xl mx-auto px-8 py-12 grid grid-cols-2 md:grid-cols-4 gap-8 text-sm">
        <div>
          <p className="text-lg font-bold tracking-tight">SIGMA</p>
          <p className="text-gray-500 mt-2 text-xs leading-relaxed max-w-[16rem]">
            AI trading signals and quantum portfolio optimization for builders.
          </p>
        </div>
        {COLUMNS.map((col) => (
          <div key={col.heading}>
            <p className="text-gray-300 font-semibold mb-3">{col.heading}</p>
            <ul className="space-y-2">
              {col.links.map((link) => (
                <li key={link.label}>
                  {link.external ? (
                    <a
                      href={link.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-gray-500 hover:text-white transition-colors"
                    >
                      {link.label}
                    </a>
                  ) : (
                    <Link
                      href={link.href}
                      className="text-gray-500 hover:text-white transition-colors"
                    >
                      {link.label}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-white/10">
        <div className="max-w-6xl mx-auto px-8 py-6 text-xs text-gray-500 flex flex-col md:flex-row md:items-center md:justify-between gap-2">
          <span>&copy; {new Date().getFullYear()} SIGMA. All rights reserved.</span>
          <span>Not investment advice. For research and engineering use.</span>
        </div>
      </div>
    </footer>
  );
}
