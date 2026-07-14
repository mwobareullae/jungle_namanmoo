import { Question } from "@phosphor-icons/react";

type QuestionIconProps = { size?: number; className?: string };

function QuestionIcon({ size = 20, className }: QuestionIconProps) {
  return <Question aria-hidden="true" className={className} size={size} weight="regular" />;
}

export default QuestionIcon;
