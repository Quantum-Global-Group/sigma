type Product = { title: string; body: string; href: string };

const GUMROAD_DASHBOARD = process.env.NEXT_PUBLIC_GUMROAD_DASHBOARD_URL;
const GUMROAD_ML = process.env.NEXT_PUBLIC_GUMROAD_ML_URL;

export function GumroadStrip() {
  const products: Product[] = [];
  if (GUMROAD_DASHBOARD) {
    products.push({
      title: "Dashboard template",
      body: "The Next.js + Tailwind dashboard shell powering SIGMA. Drop into any project.",
      href: GUMROAD_DASHBOARD,
    });
  }
  if (GUMROAD_ML) {
    products.push({
      title: "ML signal boilerplate",
      body: "FastAPI + pandas-ta + ensemble model wiring. Skip a week of plumbing.",
      href: GUMROAD_ML,
    });
  }
  if (products.length === 0) return null;

  return (
    <section className="max-w-6xl mx-auto px-8 py-16 border-t border-white/10">
      <h2 className="text-2xl md:text-3xl font-bold tracking-tight mb-3 text-center">
        Templates and boilerplates
      </h2>
      <p className="text-gray-400 text-center mb-10 max-w-2xl mx-auto">
        The same building blocks we use, packaged for you.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {products.map((p) => (
          <a
            key={p.title}
            href={p.href}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-xl border border-white/10 bg-white/5 p-6 hover:border-indigo-500/40 hover:bg-white/[0.07] transition-colors"
          >
            <h3 className="text-lg font-semibold mb-2">{p.title}</h3>
            <p className="text-gray-400 text-sm leading-relaxed">{p.body}</p>
            <p className="mt-4 text-indigo-400 text-sm font-medium">View on Gumroad &rarr;</p>
          </a>
        ))}
      </div>
    </section>
  );
}
