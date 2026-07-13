import { Minus } from "@phosphor-icons/react";

type MinusIconProps = {
  size?: number;
  className?: string;
};

function MinusIcon({ size = 20, className }: MinusIconProps) {
  return <Minus aria-hidden="true" className={className} size={size} weight="regular" />;
}

export default MinusIcon;
