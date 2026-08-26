import type { ReactNode } from "react";

/**
 * Empty state for a surface that has no data pipeline behind it yet. Deliberately shows
 * nothing that could be mistaken for real operational data.
 */
export function Placeholder({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children?: ReactNode;
}) {
  return (
    <section className="space-y-4">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">{title}</h1>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">{description}</p>
      </header>
      <div className="rounded border border-dashed border-neutral-300 p-6 text-sm text-neutral-600 dark:border-neutral-700 dark:text-neutral-400">
        <p className="font-medium">Not implemented yet</p>
        <p className="mt-1">
          No data is loaded. This surface is a placeholder until the corresponding
          capability is built.
        </p>
      </div>
      {children}
    </section>
  );
}
