import type { ReactNode } from "react";

type Tone = "neutral" | "info" | "warn" | "danger";

const TONES: Record<Tone, string> = {
  neutral: "border-neutral-300 text-neutral-700 dark:border-neutral-700 dark:text-neutral-300",
  info: "border-blue-300 text-blue-800 dark:border-blue-900 dark:text-blue-300",
  warn: "border-amber-300 text-amber-900 dark:border-amber-900 dark:text-amber-300",
  danger: "border-red-300 text-red-800 dark:border-red-900 dark:text-red-300",
};

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: Tone;
  children: ReactNode;
}) {
  return (
    <span
      className={`inline-block rounded border px-2 py-0.5 text-xs whitespace-nowrap ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}
