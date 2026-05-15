import { notFound } from "next/navigation";
import Link from "next/link";
import { compileMDX } from "next-mdx-remote/rsc";
import { DOC_MANIFEST, getDoc, listDocs, readDocSource } from "@/lib/docs";
import { DocsSidebar } from "@/components/docs/DocsSidebar";
import { mdxComponents } from "@/components/docs/MdxComponents";

export const dynamicParams = false;

export function generateStaticParams() {
  return DOC_MANIFEST.map((doc) => ({ slug: doc.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const doc = getDoc(slug);
  if (!doc) return {};
  return {
    title: `${doc.title} — SIGMA Docs`,
    description: doc.description,
  };
}

export default async function DocPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const doc = getDoc(slug);
  if (!doc) notFound();

  const source = await readDocSource(slug);
  if (!source) notFound();

  const { content } = await compileMDX({
    source,
    components: mdxComponents,
    options: { parseFrontmatter: false },
  });

  const docs = listDocs();
  const idx = docs.findIndex((d) => d.slug === slug);
  const prev = idx > 0 ? docs[idx - 1] : null;
  const next = idx >= 0 && idx < docs.length - 1 ? docs[idx + 1] : null;

  return (
    <main className="max-w-6xl mx-auto px-8 py-12">
      <div className="md:flex md:gap-10">
        <DocsSidebar activeSlug={slug} />
        <article className="flex-1 mt-8 md:mt-0 min-w-0">
          <p className="text-xs text-indigo-400 font-medium uppercase tracking-wider mb-2">Docs</p>
          {content}
          <nav className="mt-16 pt-8 border-t border-white/10 grid grid-cols-2 gap-4 text-sm">
            <div>
              {prev && (
                <Link
                  href={`/docs/${prev.slug}`}
                  className="block rounded-lg border border-white/10 bg-white/5 p-4 hover:bg-white/[0.07] transition-colors"
                >
                  <span className="text-gray-500">Previous</span>
                  <span className="block text-white font-medium mt-1">{prev.title}</span>
                </Link>
              )}
            </div>
            <div className="text-right">
              {next && (
                <Link
                  href={`/docs/${next.slug}`}
                  className="block rounded-lg border border-white/10 bg-white/5 p-4 hover:bg-white/[0.07] transition-colors"
                >
                  <span className="text-gray-500">Next</span>
                  <span className="block text-white font-medium mt-1">{next.title}</span>
                </Link>
              )}
            </div>
          </nav>
        </article>
      </div>
    </main>
  );
}
