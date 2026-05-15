import { NextRequest, NextResponse } from "next/server";
import { getStripe } from "@/lib/stripe";

export async function POST(req: NextRequest) {
  const sig = req.headers.get("stripe-signature");
  if (!sig) {
    return NextResponse.json({ error: "Missing stripe-signature" }, { status: 400 });
  }

  const rawBody = await req.bytes();
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET ?? "";

  let event;
  try {
    event = getStripe().webhooks.constructEvent(Buffer.from(rawBody), sig, webhookSecret);
  } catch {
    return NextResponse.json({ error: "Webhook signature verification failed" }, { status: 400 });
  }

  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const internalSecret = process.env.INTERNAL_SECRET ?? "";

  switch (event.type) {
    case "customer.subscription.created":
    case "customer.subscription.updated": {
      const sub = event.data.object as { customer: string; status: string; items?: { data: Array<{ price: { id: string } }> } };
      const plan = _priceIdToPlan(sub.items?.data?.[0]?.price?.id ?? "");
      await _syncPlan(apiBase, internalSecret, sub.customer as string, plan);
      break;
    }
    case "customer.subscription.deleted": {
      const sub = event.data.object as { customer: string };
      await _syncPlan(apiBase, internalSecret, sub.customer as string, "free");
      break;
    }
    default:
      break;
  }

  return NextResponse.json({ received: true });
}

function _priceIdToPlan(priceId: string): string {
  const pro = process.env.STRIPE_PRICE_PRO ?? "";
  const enterprise = process.env.STRIPE_PRICE_ENTERPRISE ?? "";
  if (priceId === pro) return "pro";
  if (priceId === enterprise) return "enterprise";
  return "free";
}

async function _syncPlan(apiBase: string, secret: string, stripeCustomerId: string, plan: string): Promise<void> {
  try {
    await fetch(`${apiBase}/internal/users/sync-plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Internal-Secret": secret },
      body: JSON.stringify({ stripe_customer_id: stripeCustomerId, plan }),
    });
  } catch (err) {
    console.error("Failed to sync plan:", err);
  }
}
