import type { ReactNode } from "react";

/**
 * One progressive-disclosure control, used everywhere detail is hidden.
 *
 * Native `<details>` rather than React state: keyboard accessible and announced by
 * screen readers without any ARIA of our own, works before hydration, and cannot
 * desynchronise between server and client render. Every page that hides depth uses this,
 * so expanding behaves identically wherever a reader meets it.
 *
 * The rule this enforces: a default view carries what a decision needs, and everything
 * that supports *auditing* that decision — provenance, raw evidence, methodology — is one
 * predictable click away. Nothing is deleted to achieve density.
 */
export function Disclosure({
  summary,
  hint,
  children,
  defaultOpen = false,
}: {
  /** What is inside. Written as a noun phrase, not "click here". */
  summary: string;
  /** Optional count or scale, so a reader knows the cost of opening before they do. */
  hint?: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details
      open={defaultOpen}
      className="group rounded border border-neutral-200 dark:border-neutral-800"
    >
      <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-100">
        <span
          aria-hidden
          className="text-xs text-neutral-400 transition-transform group-open:rotate-90 dark:text-neutral-600"
        >
          ▶
        </span>
        <span>{summary}</span>
        {hint && <span className="text-xs text-neutral-500">{hint}</span>}
      </summary>
      <div className="border-t border-neutral-200 px-3 py-3 dark:border-neutral-800">
        {children}
      </div>
    </details>
  );
}
