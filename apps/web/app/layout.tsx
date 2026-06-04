import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";

import { isClerkConfigured } from "@/lib/auth-config";
import "./globals.css";

export const metadata: Metadata = {
  title: "SIGMA — AI Trading Signals",
  description: "AI-powered trading signals with quantum portfolio optimization",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const body = (
    <html lang="en">
      <body>{children}</body>
    </html>
  );

  if (!isClerkConfigured()) {
    return body;
  }

  return <ClerkProvider>{body}</ClerkProvider>;
}
