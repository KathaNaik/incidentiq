/**
 * The investigation loading state.
 *
 * The model call takes several seconds and the application observes exactly one request
 * — it cannot see the model move between stages. So this describes what the *request*
 * covers and does not pretend to track it: no progress bar, no stage ticking over, no
 * invented percentage. The list is what the single call does, not a live trace of it.
 */
export function InvestigationPending() {
  return (
    <div className="rounded border border-neutral-300 p-4 dark:border-neutral-700">
      <p className="text-sm font-medium">Investigating…</p>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
        Evidence has been collected and sent to the model in one request. This usually
        takes several seconds.
      </p>
      <ul className="mt-3 space-y-1 text-sm text-neutral-500">
        <li>· Correlated tickets, deployments, service health and error signatures</li>
        <li>· Similar past incidents from the historical corpus</li>
        <li>· One model call, then validation of every citation it returns</li>
      </ul>
      <p className="mt-3 text-xs text-neutral-500">
        Everything above this section is deterministic and already final.
      </p>
    </div>
  );
}
