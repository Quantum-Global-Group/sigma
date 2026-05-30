/** True when real Clerk keys are set (not blank / REPLACE_ME placeholders). */
export function isClerkConfigured(): boolean {
  const publishableKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY?.trim() ?? "";
  const secretKey = process.env.CLERK_SECRET_KEY?.trim() ?? "";

  if (!publishableKey || !secretKey) return false;
  if (publishableKey.includes("REPLACE_ME") || secretKey.includes("REPLACE_ME")) {
    return false;
  }

  return publishableKey.startsWith("pk_") && secretKey.startsWith("sk_");
}

/** Stable dev user id when Clerk is disabled locally. */
export const DEV_USER_ID = "dev_local_user";
