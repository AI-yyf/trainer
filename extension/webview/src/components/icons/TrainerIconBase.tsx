import type { ReactNode, SVGProps } from "react";

/**
 * §四十六 Premium Soft Outline + Selective Fill icon base.
 *
 * Inactive: clean outline (currentColor stroke, no fill).
 * Active: outline + a tiny filled semantic element (CSS `--icon-fill`).
 *
 * One five-step optical scale is the only sanctioned source of icon sizes.
 * Dense chrome uses 12/14, controls 16, headers 18 and primary navigation 20.
 * Off-scale sizes (11, 13, 15, …) read as accidents next to their neighbours,
 * so the icon contract test rejects them.
 */
export const TRAINER_ICON_SIZES = {
  micro: 12,
  inline: 14,
  control: 16,
  header: 18,
  nav: 20,
} as const;

export type TrainerIconSize = (typeof TRAINER_ICON_SIZES)[keyof typeof TRAINER_ICON_SIZES];

export interface TrainerIconProps extends Omit<SVGProps<SVGSVGElement>, "children"> {
  children?: ReactNode;
  /** Optical size — use TRAINER_ICON_SIZES, never a raw one-off value. */
  size?: TrainerIconSize;
  title?: string;
  /** When true, a per-icon fill element is shown (§四十六 selective fill). */
  active?: boolean;
}

export function TrainerIconBase({
  children,
  size = 20,
  title,
  active = false,
  viewBox = "0 0 20 20",
  ...props
}: TrainerIconProps & { active?: boolean }) {
  // Keep the rendered stroke optically equal across the 16/20/24 working
  // canvases. 1.4 units is correct on the 20-box; a 24-box glyph rendered at
  // 14–16px would otherwise draw a hairline next to a 16-box neighbour.
  const strokeWidth = viewBox === "0 0 24 24" ? 1.9 : 1.4;
  return (
    <svg
      aria-hidden={title ? undefined : true}
      className={active ? "trainer-icon is-active" : "trainer-icon"}
      data-active={active || undefined}
      fill="none"
      height={size}
      focusable="false"
      role={title ? "img" : "presentation"}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={strokeWidth}
      shapeRendering="geometricPrecision"
      viewBox={viewBox}
      width={size}
      vectorEffect="non-scaling-stroke"
      {...props}
    >
      {title ? <title>{title}</title> : null}
      {children}
    </svg>
  );
}
