import type { ReactNode } from "react";

export type BadgeTone = "primary" | "success" | "warning" | "danger" | "neutral";

const TONE_CLASSES: Record<BadgeTone, string> = {
  primary: "bg-[#EFF6FF] text-[#1D4ED8] border-blue-200",
  success: "bg-[#ECFDF5] text-[#059669] border-emerald-200",
  warning: "bg-[#FFFBEB] text-[#D97706] border-amber-200",
  danger: "bg-[#FEF2F2] text-[#DC2626] border-red-200",
  neutral: "bg-slate-100 text-slate-700 border-slate-200",
};

interface StatusBadgeProps {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
}

export function StatusBadge({
  tone = "neutral",
  children,
  className = "",
}: StatusBadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${TONE_CLASSES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
