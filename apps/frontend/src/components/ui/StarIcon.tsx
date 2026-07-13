import { Star } from "@phosphor-icons/react";

type StarIconProps = {
  size?: number;
  className?: string;
};

function StarIcon({ size = 16, className }: StarIconProps) {
  return <Star aria-hidden="true" className={className} size={size} weight="fill" />;
}

export default StarIcon;
