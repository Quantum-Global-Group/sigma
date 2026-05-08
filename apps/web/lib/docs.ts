import fs from "node:fs/promises";
import path from "node:path";

export type DocMeta = {
  slug: string;
  title: string;
  description: string;
  order: number;
};

export const DOC_MANIFEST: DocMeta[] = [
  {
    slug: "quick-start",
    title: "Quick Start",
    description: "Run SIGMA locally and call your first signal in five minutes.",
    order: 1,
  },
  {
    slug: "authentication",
    title: "Authentication",
    description: "API key format, headers, and how keys are validated.",
    order: 2,
  },
  {
    slug: "endpoints",
    title: "Endpoints",
    description: "Reference for every public REST endpoint and response shape.",
    order: 3,
  },
  {
    slug: "rate-limits",
    title: "Rate Limits",
    description: "Per-plan call budgets, burst caps, and the headers we return.",
    order: 4,
  },
  {
    slug: "examples",
    title: "Examples",
    description: "Copy-paste recipes in curl, Python, and TypeScript.",
    order: 5,
  },
];

const CONTENT_DIR = path.join(process.cwd(), "content", "docs");

export function listDocs(): DocMeta[] {
  return [...DOC_MANIFEST].sort((a, b) => a.order - b.order);
}

export function getDoc(slug: string): DocMeta | undefined {
  return DOC_MANIFEST.find((d) => d.slug === slug);
}

export async function readDocSource(slug: string): Promise<string | null> {
  try {
    return await fs.readFile(path.join(CONTENT_DIR, `${slug}.mdx`), "utf8");
  } catch {
    return null;
  }
}
