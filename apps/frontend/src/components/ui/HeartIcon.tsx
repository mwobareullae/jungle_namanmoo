import { Heart } from "@phosphor-icons/react";

type HeartIconProps = {
  size?: number;
  filled?: boolean;
  className?: string;
};

function HeartIcon({ size = 12, filled = false, className }: HeartIconProps) {
  return <Heart aria-hidden="true" className={className} size={size} weight={filled ? "fill" : "regular"} />;
}

export default HeartIcon;
