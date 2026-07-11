import type { CSSProperties, ElementType, HTMLAttributes } from "react";

type SkeletonProps<T extends ElementType = "span"> = {
  as?: T;
  className?: string;
  style?: CSSProperties;
} & Omit<HTMLAttributes<HTMLElement>, "style">;

function Skeleton<T extends ElementType = "span">({ as, className, style, ...props }: SkeletonProps<T>) {
  const Component = (as ?? "span") as ElementType;

  return <Component aria-hidden="true" className={`skeleton-shimmer ${className ?? ""}`.trim()} style={style} {...props} />;
}

export default Skeleton;
