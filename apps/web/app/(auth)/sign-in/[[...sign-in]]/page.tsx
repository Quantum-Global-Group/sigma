import { SignIn } from "@clerk/nextjs";

import { ClerkUnavailable } from "@/components/auth/ClerkUnavailable";
import { isClerkConfigured } from "@/lib/auth-config";

export default function SignInPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950">
      {isClerkConfigured() ? <SignIn /> : <ClerkUnavailable mode="sign-in" />}
    </div>
  );
}
