import type { ReactNode, SVGProps } from "react";

export interface IconBaseProps extends Omit<SVGProps<SVGSVGElement>, "children"> {
  children: ReactNode;
  size?: number;
  title?: string;
}

export function IconBase({
  children,
  size = 16,
  title,
  viewBox = "0 0 16 16",
  ...props
}: IconBaseProps) {
  return (
    <svg
      aria-hidden={title ? undefined : true}
      fill="none"
      height={size}
      focusable="false"
      role={title ? "img" : "presentation"}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={1.55}
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
