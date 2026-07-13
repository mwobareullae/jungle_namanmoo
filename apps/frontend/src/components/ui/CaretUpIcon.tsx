import { CaretUp } from "@phosphor-icons/react";

type CaretUpIconProps = { size?: number; className?: string };

function CaretUpIcon({ size = 24, className }: CaretUpIconProps) {
  return <CaretUp aria-hidden="true" className={className} size={size} weight="regular" />;
}

export default CaretUpIcon;
