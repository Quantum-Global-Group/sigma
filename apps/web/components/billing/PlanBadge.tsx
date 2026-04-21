import { cn } from "@/lib/utils";

const PLAN_STYLES: Record<string, string> = {
  free: "bg-gray-100 text-gray-700",
  pro: "bg-indigo-100 text-indigo-700",
  enterprise: "bg-purple-100 text-purple-700",
};

export function PlanBadge({ plan }: { plan: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium capitalize",
        PLAN_STYLES[plan] ?? PLAN_STYLES.free
      )}
    >
      {plan}
    </span>
  );
}
