import { auth, currentUser } from "@clerk/nextjs/server";

import { DEV_USER_ID, isClerkConfigured } from "@/lib/auth-config";

export async function getAuthUserId(): Promise<string | null> {
  if (!isClerkConfigured()) return DEV_USER_ID;
  const { userId } = await auth();
  return userId;
}

export async function requireAuth() {
  const userId = await getAuthUserId();
  if (!userId) throw new Error("Unauthenticated");
  return userId;
}

export async function getServerUser() {
  if (!isClerkConfigured()) return null;
  return currentUser();
}
