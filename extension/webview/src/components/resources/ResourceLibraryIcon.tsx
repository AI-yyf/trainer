import { TrainerIconBase } from "../icons/TrainerIconBase";

/** One optical grid for library folders and documents. */
export function ResourceLibraryIcon({ kind, size = 20 }: { kind: string; size?: number }) {
  if (kind === "folder") return <TrainerIconBase size={size}>
    <path d="M2.5 6.5h5l1.5-2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-10a2 2 0 0 1-2-2z" fill="currentColor" opacity=".08" stroke="none" />
    <path d="M2.5 6.5V5a1.5 1.5 0 0 1 1.5-1.5h3l2 2h6.5A1.5 1.5 0 0 1 17 7v7.5a2 2 0 0 1-2 2H4.5a2 2 0 0 1-2-2z" />
    <path d="M2.5 7.5H17" opacity=".45" />
  </TrainerIconBase>;
  if (kind === "url") return <TrainerIconBase size={size}>
    <circle cx="10" cy="10" r="6.8" /><path d="M3.5 10h13M10 3.2c-3.5 3.5-3.5 10.1 0 13.6M10 3.2c3.5 3.5 3.5 10.1 0 13.6" />
  </TrainerIconBase>;
  return <TrainerIconBase size={size}>
    <path d="M6 2.8h6l3 3v9.4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4.8a2 2 0 0 1 2-2z" />
    <path d="M12 2.8v3h3" opacity=".6" />
    {kind === "code" ? <><path d="m7.4 9-1.8 1.8 1.8 1.8m4.8-3.6 1.8 1.8-1.8 1.8m-1.4-4.5-1.6 5.4" /></>
      : kind === "markdown" ? <><path d="M6.8 13V9l2.2 2 2.2-2v4M13.1 10.4v2.6" /></>
      : <><path d="M7 9h5M7 12h5M7 15h3" opacity=".7" /></>}
  </TrainerIconBase>;
}
