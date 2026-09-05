import { IconBase, type IconBaseProps } from "./IconBase";

type CoachIconProps = Omit<IconBaseProps, "children">;

export function SettingsIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M6.6 1.8h2.8l.4 1.7c.4.1.8.3 1.1.6l1.7-.6 1.2 2.1-1.3 1.1c.1.4.1.8.1 1.3s0 .9-.1 1.3l1.3 1.1-1.2 2.1-1.7-.6c-.3.3-.7.5-1.1.6l-.4 1.7H6.6l-.4-1.7c-.4-.1-.8-.3-1.1-.6l-1.7.6-1.2-2.1 1.3-1.1A5 5 0 0 1 3.4 8c0-.4 0-.9.1-1.3L2.2 5.6 3.4 3.5l1.7.6c.3-.3.7-.5 1.1-.6z" />
      <circle cx="8" cy="8" r="1.9" />
    </IconBase>
  );
}

export function ComposeIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M3.4 11.8 4 9.4 10.7 2.7a1.2 1.2 0 0 1 1.7 0l.9.9a1.2 1.2 0 0 1 0 1.7L6.6 12 4.2 12.6z" />
      <path d="M9.9 3.5 12.5 6.1" />
    </IconBase>
  );
}

export function SendIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M8 12.25V3.75" />
      <path d="M4.75 7.15 8 3.75l3.25 3.4" />
    </IconBase>
  );
}

export function CommandIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M3.5 5h9" />
      <path d="M3.5 8h9" />
      <path d="M3.5 11h6" />
    </IconBase>
  );
}

export function FileIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M5 2.5h4l2 2v9H5z" />
      <path d="M9 2.5v2h2" />
      <path d="M6.5 7h3" />
      <path d="M6.5 9h3" />
      <path d="M6.5 11h2.2" />
    </IconBase>
  );
}

export function UploadIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M8 11.4V4.4" />
      <path d="M5.2 7.1 8 4.4l2.8 2.7" />
      <path d="M3.4 12.4h9.2" />
    </IconBase>
  );
}

export function AttachmentIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M11.6 6.2 7 10.8a2.6 2.6 0 1 1-3.7-3.7l4.9-4.9a1.9 1.9 0 1 1 2.7 2.7L6.4 9.4a1.1 1.1 0 1 1-1.6-1.6l3.8-3.8" />
    </IconBase>
  );
}

export function CloseIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="m4.2 4.2 7.6 7.6" />
      <path d="m11.8 4.2-7.6 7.6" />
    </IconBase>
  );
}

export function PlusIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M8 3.5v9" />
      <path d="M3.5 8h9" />
    </IconBase>
  );
}

export function SelectionIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M3.5 5V3.5H5" />
      <path d="M11 3.5h1.5V5" />
      <path d="M12.5 11V12.5H11" />
      <path d="M5 12.5H3.5V11" />
      <path d="M6 5.5h4v4H6z" />
    </IconBase>
  );
}

export function DiagnosticsIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M8 2.6 13.1 12H2.9L8 2.6z" />
      <path d="M8 5.9v2.8" />
      <circle cx="8" cy="10.5" r="0.8" fill="currentColor" stroke="none" />
    </IconBase>
  );
}

export function RelatedFilesIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <circle cx="4.2" cy="4.2" r="1.4" />
      <circle cx="11.8" cy="4.2" r="1.4" />
      <circle cx="8" cy="11.7" r="1.4" />
      <path d="M5.5 5.2 7.2 9.4" />
      <path d="M10.5 5.2 8.8 9.4" />
    </IconBase>
  );
}

export function ContextLayersIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <rect x="3.2" y="3.2" width="7.2" height="7.2" rx="1.2" />
      <path d="M6.6 11.6h5.2a1.2 1.2 0 0 0 1.2-1.2V5.4" />
    </IconBase>
  );
}

export function FollowIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <circle cx="8" cy="8" r="3.2" />
      <path d="M8 1.7v2.1" />
      <path d="M8 12.2v2.1" />
      <path d="M1.7 8h2.1" />
      <path d="M12.2 8h2.1" />
    </IconBase>
  );
}

export function InsightIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M8 2.8 8.8 5.2 11.2 6 8.8 6.8 8 9.2 7.2 6.8 4.8 6 7.2 5.2z" />
      <path d="M12.4 2.8v1.6" />
      <path d="M13.2 3.6h-1.6" />
      <path d="M11.2 10.7v1.4" />
      <path d="M11.9 11.4h-1.4" />
    </IconBase>
  );
}

export function PlanIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M4.2 3.3h7.6" />
      <path d="M4.2 6.5h7.6" />
      <path d="M4.2 9.7h4.5" />
      <path d="M3 2.2h10v11.6H3z" />
    </IconBase>
  );
}

export function ReviewIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M12.1 7.9a4.1 4.1 0 1 1-1.1-2.8" />
      <path d="M10.7 2.8h2.5v2.5" />
      <path d="M13.2 2.8 9.9 6.1" />
    </IconBase>
  );
}

export function ArrowRightIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M3 8h9.2" />
      <path d="m9 4.3 3.7 3.7L9 11.7" />
    </IconBase>
  );
}

export function ChevronDownIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="m4.5 6.5 3.5 3.5 3.5-3.5" />
    </IconBase>
  );
}

export function ChevronRightIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="m6.5 4.5 3.5 3.5-3.5 3.5" />
    </IconBase>
  );
}

export function ChevronUpIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="m4.5 9.5 3.5-3.5 3.5 3.5" />
    </IconBase>
  );
}

export function SearchIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <circle cx="7" cy="7" r="3.6" />
      <path d="M9.8 9.8 12.5 12.5" />
    </IconBase>
  );
}

export function RefreshIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M12.1 6V2.9H9" />
      <path d="M12 8A4 4 0 1 1 10.8 5" />
    </IconBase>
  );
}

export function FolderIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M2.8 4.4h3l1.2 1.3h6.2v6.1H2.8z" />
      <path d="M2.8 4h3.6l1 1.1h5.8" />
    </IconBase>
  );
}

export function LinkIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M6.2 9.8 4.9 11a2 2 0 1 1-2.8-2.8L4 6.4a2 2 0 0 1 2.8 0" />
      <path d="m9.8 6.2 1.3-1.3a2 2 0 0 1 2.8 2.8L12 9.6a2 2 0 0 1-2.8 0" />
      <path d="M5.9 10.1 10.1 5.9" />
    </IconBase>
  );
}

export function TrashIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M4.5 5.2h7" />
      <path d="M6.1 5.2V3.8h3.8v1.4" />
      <path d="m5.2 5.2.5 6.8h4.6l.5-6.8" />
      <path d="M7 6.8v3.7" />
      <path d="M9 6.8v3.7" />
    </IconBase>
  );
}

export function CheckIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="m3.5 8.2 2.9 2.9 6.1-6.2" />
    </IconBase>
  );
}

export function CheckMarkIcon(props: CoachIconProps) {
  return <CheckIcon {...props} />;
}

export function XMarkIcon(props: CoachIconProps) {
  return <CloseIcon {...props} />;
}

export function WarningIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M8 2.6 13.1 12H2.9L8 2.6z" />
      <path d="M8 5.7v2.8" />
      <circle cx="8" cy="10.4" r="0.8" fill="currentColor" stroke="none" />
    </IconBase>
  );
}

export function EyeIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M1.9 8s2.2-3.6 6.1-3.6S14.1 8 14.1 8s-2.2 3.6-6.1 3.6S1.9 8 1.9 8z" />
      <circle cx="8" cy="8" r="1.9" />
    </IconBase>
  );
}

export function PlayIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M5.4 4.2 11.4 8l-6 3.8z" fill="currentColor" stroke="none" />
    </IconBase>
  );
}

export function SquareIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <rect x="4" y="4" width="8" height="8" rx="1.4" />
    </IconBase>
  );
}

export function RadioButtonEmptyIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <circle cx="8" cy="8" r="4.2" />
    </IconBase>
  );
}

export function RadioButtonIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <circle cx="8" cy="8" r="4.2" />
      <circle cx="8" cy="8" r="1.8" fill="currentColor" stroke="none" />
    </IconBase>
  );
}

export function BookOpenIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M3.4 4.2h3.3c1 0 1.8.8 1.8 1.8v6.2H5.2c-1 0-1.8-.8-1.8-1.8z" />
      <path d="M12.6 4.2H9.3c-1 0-1.8.8-1.8 1.8v6.2h3.3c1 0 1.8-.8 1.8-1.8z" />
    </IconBase>
  );
}

export function BooksIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M3 4.4h3.4l1.2 1.3H13v6.8H3z" />
    </IconBase>
  );
}

export function BrainIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M6.2 3.2a2.1 2.1 0 0 0-2.9 1.9v.4a2 2 0 0 0-.8 3.2 2.4 2.4 0 0 0 2.3 3.8H7V4.8a1.6 1.6 0 0 0-.8-1.6z" />
      <path d="M9.8 3.2a2.1 2.1 0 0 1 2.9 1.9v.4a2 2 0 0 1 .8 3.2 2.4 2.4 0 0 1-2.3 3.8H9V4.8c0-.7.3-1.3.8-1.6z" />
      <path d="M6.4 6.2H4.8" />
      <path d="M6.4 8.6H4.5" />
      <path d="M9.6 6.2h1.6" />
      <path d="M9.6 8.6h1.9" />
    </IconBase>
  );
}

export function LightBulbIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M5.4 9.9c-.8-.7-1.3-1.7-1.3-2.8A3.9 3.9 0 0 1 8 3.2a3.9 3.9 0 0 1 3.9 3.9c0 1.1-.5 2.1-1.3 2.8-.4.3-.6.8-.7 1.3H6.1c-.1-.5-.3-1-.7-1.3z" />
      <path d="M6.3 12.1h3.4" />
      <path d="M6.8 13.5h2.4" />
    </IconBase>
  );
}

export function LightningIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M8.9 2.8 4.8 8h2.8l-.5 5.2 4.1-5.2H8.4z" />
    </IconBase>
  );
}

export function SparklesIcon(props: CoachIconProps) {
  return <InsightIcon {...props} />;
}

export function TrophyIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M5.2 3.3h5.6v2.6A2.8 2.8 0 0 1 8 8.7a2.8 2.8 0 0 1-2.8-2.8z" />
      <path d="M5.2 4.1H3.7a1.6 1.6 0 0 0 1.6 1.6H5.7" />
      <path d="M10.8 4.1h1.5a1.6 1.6 0 0 1-1.6 1.6H10.3" />
      <path d="M8 8.7v2.3" />
      <path d="M6.2 13h3.6" />
      <path d="M6.8 11h2.4" />
    </IconBase>
  );
}

export function TargetIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <circle cx="8" cy="8" r="4.8" />
      <circle cx="8" cy="8" r="2.5" />
      <circle cx="8" cy="8" r="0.9" fill="currentColor" stroke="none" />
    </IconBase>
  );
}

export function FireIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <path d="M8.2 2.8c.4 1.7-.7 2.6-1.4 3.4-.8.9-1.5 1.8-1.5 3a2.7 2.7 0 0 0 5.4 0c0-1.5-.9-2.5-1.8-3.5-.5-.6-1.1-1.3-.7-2.9z" />
    </IconBase>
  );
}

export function CompassIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <circle cx="8" cy="8" r="4.8" />
      <path d="m9.9 6.1-1.5 3.8-2.3.8 1.5-3.8z" />
    </IconBase>
  );
}

export function LaptopIcon(props: CoachIconProps) {
  return (
    <IconBase {...props}>
      <rect x="3.4" y="3.4" width="9.2" height="6.1" rx="1.1" />
      <path d="M2.6 11.3h10.8" />
      <path d="M5.8 13h4.4" />
    </IconBase>
  );
}

export function PageIcon(props: CoachIconProps) {
  return <FileIcon {...props} />;
}

export function GearIcon(props: CoachIconProps) {
  return <SettingsIcon {...props} />;
}

export function TrainerMarkIcon(props: CoachIconProps) {
  return (
    <IconBase {...props} viewBox="0 0 128 128">
      <rect x="14" y="14" width="100" height="100" rx="26" fill="currentColor" opacity="0.1" />
      <rect
        x="18"
        y="18"
        width="92"
        height="92"
        rx="22"
        stroke="currentColor"
        strokeOpacity="0.2"
        strokeWidth="4"
      />
      <path d="M39 44H79" strokeWidth="7" strokeLinecap="round" />
      <path d="M39 64H88" strokeWidth="7" strokeLinecap="round" />
      <path d="M39 84H61" strokeWidth="7" strokeLinecap="round" opacity="0.9" />
      <path d="M80 78 91 89 80 100" strokeWidth="6.5" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="92" cy="38" r="4.5" fill="currentColor" opacity="0.24" stroke="none" />
    </IconBase>
  );
}

export function ResourcesIcon(props: CoachIconProps) {
  return <BooksIcon {...props} />;
}

export function TrainingIcon(props: CoachIconProps) {
  return <TargetIcon {...props} />;
}
