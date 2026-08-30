import type { ReactNode } from "react";

/**
 * One step of the incident narrative.
 *
 * The detail page is long by necessity — it has to show what was observed, what was
 * inferred, what was proposed, and what a human then did. Numbered, consistently
 * titled sections keep that readable as a sequence rather than a pile of panels.
 */
export function Section({
  step,
  title,
  subtitle,
  children,
}: {
  step: number;
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div className="border-b border-neutral-200 pb-2 dark:border-neutral-800">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-xs text-neutral-400 tabular-nums dark:text-neutral-600">
            {String(step).padStart(2, "0")}
          </span>
          <h2 className="text-sm font-semibold tracking-wide uppercase">{title}</h2>
        </div>
        {subtitle && (
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            {subtitle}
          </p>
        )}
      </div>
      {children}
    </section>
  );
}
