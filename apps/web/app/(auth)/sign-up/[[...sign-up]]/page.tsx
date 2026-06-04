import { SignUp } from "@clerk/nextjs";

import { ClerkUnavailable } from "@/components/auth/ClerkUnavailable";
import { isClerkConfigured } from "@/lib/auth-config";

export default function SignUpPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950">
      {isClerkConfigured() ? <SignUp /> : <ClerkUnavailable mode="sign-up" />}
    </div>
  );
}
