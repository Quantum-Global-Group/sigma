import Link from "next/link";
import { listDocs } from "@/lib/docs";

export function DocsSidebar({ activeSlug }: { activeSlug?: string }) {
  const docs = listDocs();
  return (
    <aside className="md:w-56 md:shrink-0 border-b md:border-b-0 md:border-r border-white/10 md:pr-6 md:py-2">
      <p className="text-xs uppercase tracking-wider text-gray-500 mb-3">Documentation</p>
      <nav className="flex md:flex-col gap-1 overflow-x-auto md:overflow-visible">
        <Link
          href="/docs"
          className={`text-sm px-3 py-2 rounded-md transition-colors whitespace-nowrap ${
            !activeSlug ? "bg-white/10 text-white" : "text-gray-400 hover:text-white hover:bg-white/5"
          }`}
        >
          Overview
        </Link>
        {docs.map((doc) => (
          <Link
            key={doc.slug}
            href={`/docs/${doc.slug}`}
            className={`text-sm px-3 py-2 rounded-md transition-colors whitespace-nowrap ${
              activeSlug === doc.slug
                ? "bg-white/10 text-white"
                : "text-gray-400 hover:text-white hover:bg-white/5"
            }`}
          >
            {doc.title}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
