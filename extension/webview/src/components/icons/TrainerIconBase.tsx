import type { ReactNode, SVGProps } from "react";

/**
 * §四十六 Premium Soft Outline + Selective Fill icon base.
 *
 * Inactive: clean outline (currentColor stroke, no fill).
 * Active: outline + a tiny filled semantic element (CSS `--icon-fill`).
 * Sizes are optical (nav 20, header 18, inline 16, status 12), not uniform.
 */
export interface TrainerIconProps extends Omit<SVGProps<SVGSVGElement>, "children"> {
  children?: ReactNode;
  /** Optical size — callers use nav=20, header=18, inline=16, status=12. */
  size?: number;
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
      strokeWidth={1.4}
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
