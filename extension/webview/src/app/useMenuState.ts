/**
 * Menu state management for the composer (§四十八: extracted from App.tsx).
 */

import { useState } from "react";

export type ContextMenu = "context" | "resources" | "model" | "history" | undefined;

/**
 * Manages which composer context menu is currently open.
 * Only one menu can be open at a time; setting the same menu toggles it off.
 */
export function useMenuState() {
  const [openMenu, setOpenMenu] = useState<ContextMenu>();
  return { openMenu, setOpenMenu };
}
