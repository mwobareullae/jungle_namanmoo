import { Robot } from "@phosphor-icons/react";

type RobotIconProps = { size?: number; className?: string };

function RobotIcon({ size = 32, className }: RobotIconProps) {
  return <Robot aria-hidden="true" className={className} size={size} weight="regular" />;
}

export default RobotIcon;
