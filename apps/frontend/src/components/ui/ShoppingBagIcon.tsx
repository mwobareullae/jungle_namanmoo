import { ShoppingBag } from "@phosphor-icons/react";

type ShoppingBagIconProps = {
  size?: number;
  className?: string;
};

function ShoppingBagIcon({ size = 12, className }: ShoppingBagIconProps) {
  return <ShoppingBag aria-hidden="true" className={className} size={size} weight="regular" />;
}

export default ShoppingBagIcon;
