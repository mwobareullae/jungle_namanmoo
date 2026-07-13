import { Plus } from "@phosphor-icons/react";

type PlusIconProps = {
  size?: number;
  className?: string;
};

function PlusIcon({ size = 20, className }: PlusIconProps) {
  return <Plus aria-hidden="true" className={className} size={size} weight="regular" />;
}

export default PlusIcon;
