/** Shown when the API could not be read. Never substitutes an empty list for a failure. */
export function ApiError({ error }: { error: string }) {
  return (
    <div className="rounded border border-red-300 p-4 text-sm dark:border-red-900">
      <p className="font-medium">Could not load data from the API</p>
      <p className="mt-1 text-neutral-600 dark:text-neutral-400">{error}</p>
      <p className="mt-2 text-neutral-600 dark:text-neutral-400">
        Start the backend with{" "}
        <code>uv run uvicorn app.main:app --reload --port 8001</code> in{" "}
        <code>apps/api</code>.
      </p>
    </div>
  );
}
