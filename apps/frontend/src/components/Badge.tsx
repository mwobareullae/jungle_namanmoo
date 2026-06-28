import type { ReactNode } from "react";

type BadgeProps = {
  children: ReactNode;
  tone?: "default" | "notice" | "risk";
};

function Badge({ children, tone = "default" }: BadgeProps) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export default Badge;
