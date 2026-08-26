"use client";

import { useEffect, useState } from "react";

import { fetchDataset } from "@/lib/api";

/**
 * Names the dataset behind everything on screen. Northstar Cloud is fictional, and the
 * banner reports what the API actually says rather than asserting it from a constant.
 */
export function DatasetBanner() {
  const [dataset, setDataset] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    fetchDataset(controller.signal)
      .then((info) => {
        if (info.synthetic) setDataset(info.name);
      })
      .catch(() => {
        // The API is unreachable, so no data is on screen to mislabel.
      });

    return () => controller.abort();
  }, []);

  if (dataset === null) return null;

  return (
    <div className="border-b border-amber-300 bg-amber-50 px-6 py-2 text-center text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
      Synthetic data — <code>{dataset}</code> development fixtures. Northstar Cloud is a
      fictional organisation; no record here is real.
    </div>
  );
}
