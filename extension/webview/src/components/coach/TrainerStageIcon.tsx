import {
  CheckMarkIcon,
  FolderIcon,
  InsightIcon,
  PlusIcon,
  SearchIcon,
  UploadIcon,
} from "../icons";
import type { TrainerStageKind } from "../../lib/trainerStage";

export function TrainerStageIcon({ kind, size = 14 }: { kind: TrainerStageKind; size?: 12 | 14 | 16 | 18 | 20 }) {
  const props = { size, "aria-hidden": true as const };
  switch (kind) {
    case "retrieve":
      return <SearchIcon {...props} />;
    case "download":
      return <UploadIcon {...props} />;
    case "organize":
      return <FolderIcon {...props} />;
    case "cards":
      return <PlusIcon {...props} />;
    case "finalize":
      return <CheckMarkIcon {...props} />;
    default:
      return <InsightIcon {...props} />;
  }
}
