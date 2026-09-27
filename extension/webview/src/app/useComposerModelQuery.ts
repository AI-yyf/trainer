/**
 * Composer model query state and filtering (§四十八: extracted from App.tsx).
 * Pure state management — no React component dependencies.
 */

import { useMemo, useState } from "react";

export interface ComposerModelMenuItem {
  label: string;
  model: string;
  [key: string]: unknown;
}

/**
 * Manages the model search query state and provides the filtered
 * provider menu items based on that query.
 */
export function useComposerModelQuery<T extends { label: string; model: string }>(
  items: T[],
) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((item) =>
      [item.label, item.model].some((value) => value.toLowerCase().includes(q)),
    );
  }, [items, query]);

  return { query, setQuery, filtered };
}
