import { CaretDown } from "@phosphor-icons/react";

type CaretDownIconProps = { size?: number; className?: string };

function CaretDownIcon({ size = 24, className }: CaretDownIconProps) {
  return <CaretDown aria-hidden="true" className={className} size={size} weight="regular" />;
}

export default CaretDownIcon;
