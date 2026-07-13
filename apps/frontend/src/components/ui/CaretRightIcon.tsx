import { CaretRight } from "@phosphor-icons/react";

type CaretRightIconProps = {
  size?: number;
  className?: string;
};

function CaretRightIcon({ size = 18, className }: CaretRightIconProps) {
  return <CaretRight aria-hidden="true" className={className} size={size} weight="regular" />;
}

export default CaretRightIcon;
