import Link from "next/link";
import { listDocs } from "@/lib/docs";
import { DocsSidebar } from "@/components/docs/DocsSidebar";

export const metadata = {
  title: "SIGMA — Docs",
  description: "Quick start, authentication, endpoints, rate limits, and examples.",
};

export default function DocsIndexPage() {
  const docs = listDocs();
  return (
    <main className="max-w-6xl mx-auto px-8 py-12">
      <div className="md:flex md:gap-10">
        <DocsSidebar />
        <article className="flex-1 mt-8 md:mt-0">
          <h1 className="text-4xl font-bold tracking-tight mb-4">Documentation</h1>
          <p className="text-gray-400 mb-10 max-w-2xl">
            Everything you need to call the SIGMA API and run it locally. Pick a topic to get started.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {docs.map((doc) => (
              <Link
                key={doc.slug}
                href={`/docs/${doc.slug}`}
                className="rounded-xl border border-white/10 bg-white/5 p-5 hover:border-indigo-500/40 hover:bg-white/[0.07] transition-colors"
              >
                <p className="text-xs text-indigo-400 font-medium uppercase tracking-wider mb-2">
                  {String(doc.order).padStart(2, "0")}
                </p>
                <h2 className="text-lg font-semibold mb-1">{doc.title}</h2>
                <p className="text-sm text-gray-400 leading-relaxed">{doc.description}</p>
              </Link>
            ))}
          </div>
        </article>
      </div>
    </main>
  );
}
