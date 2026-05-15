import type { ComponentPropsWithoutRef } from "react";
import Link from "next/link";

function isInternal(href: string | undefined): href is string {
  return !!href && (href.startsWith("/") || href.startsWith("#"));
}

export const mdxComponents = {
  h1: (props: ComponentPropsWithoutRef<"h1">) => (
    <h1 className="text-4xl font-bold tracking-tight mt-2 mb-6" {...props} />
  ),
  h2: (props: ComponentPropsWithoutRef<"h2">) => (
    <h2 className="text-2xl font-semibold tracking-tight mt-12 mb-4 border-t border-white/10 pt-8" {...props} />
  ),
  h3: (props: ComponentPropsWithoutRef<"h3">) => (
    <h3 className="text-lg font-semibold mt-8 mb-3" {...props} />
  ),
  p: (props: ComponentPropsWithoutRef<"p">) => (
    <p className="text-gray-300 leading-relaxed my-4" {...props} />
  ),
  ul: (props: ComponentPropsWithoutRef<"ul">) => (
    <ul className="list-disc pl-6 my-4 space-y-2 text-gray-300" {...props} />
  ),
  ol: (props: ComponentPropsWithoutRef<"ol">) => (
    <ol className="list-decimal pl-6 my-4 space-y-2 text-gray-300" {...props} />
  ),
  li: (props: ComponentPropsWithoutRef<"li">) => <li className="leading-relaxed" {...props} />,
  a: ({ href, children, ...rest }: ComponentPropsWithoutRef<"a">) =>
    isInternal(href) ? (
      <Link href={href} className="text-indigo-400 hover:text-indigo-300 underline underline-offset-2">
        {children}
      </Link>
    ) : (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-indigo-400 hover:text-indigo-300 underline underline-offset-2"
        {...rest}
      >
        {children}
      </a>
    ),
  code: (props: ComponentPropsWithoutRef<"code">) => (
    <code
      className="rounded bg-white/10 px-1.5 py-0.5 text-[0.85em] font-mono text-indigo-200"
      {...props}
    />
  ),
  pre: (props: ComponentPropsWithoutRef<"pre">) => (
    <pre
      className="rounded-lg border border-white/10 bg-black/40 p-4 my-6 overflow-x-auto text-sm font-mono text-gray-200"
      {...props}
    />
  ),
  table: (props: ComponentPropsWithoutRef<"table">) => (
    <div className="my-6 overflow-x-auto">
      <table className="w-full text-sm border border-white/10 rounded-lg" {...props} />
    </div>
  ),
  thead: (props: ComponentPropsWithoutRef<"thead">) => (
    <thead className="bg-white/5 text-left" {...props} />
  ),
  th: (props: ComponentPropsWithoutRef<"th">) => (
    <th className="px-3 py-2 font-semibold border-b border-white/10" {...props} />
  ),
  td: (props: ComponentPropsWithoutRef<"td">) => (
    <td className="px-3 py-2 border-b border-white/10 text-gray-300" {...props} />
  ),
  hr: () => <hr className="my-10 border-white/10" />,
  blockquote: (props: ComponentPropsWithoutRef<"blockquote">) => (
    <blockquote className="my-6 border-l-2 border-indigo-500 pl-4 text-gray-300 italic" {...props} />
  ),
};
