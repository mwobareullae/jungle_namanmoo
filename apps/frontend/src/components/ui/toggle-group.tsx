import * as ToggleGroupPrimitive from "@radix-ui/react-toggle-group";
import { type ComponentProps } from "react";

function ToggleGroup(props: ComponentProps<typeof ToggleGroupPrimitive.Root>) {
  return <ToggleGroupPrimitive.Root {...props} />;
}

type ToggleGroupItemTone = "accent" | "mint" | "danger" | "neutral";

// 페이지마다 이미 있던 선택 상태 색이 달라서 tone으로 분리해서 그대로 보존한다.
// accent = 회원가입 피부프로필(SignupSkinProfilePage)의 선택 상태 색, 나머지는 마이페이지 피부프로필의 색.
const toneClassName: Record<ToggleGroupItemTone, string> = {
  accent:
    "data-[state=off]:border-[rgba(0,0,0,0.07)] data-[state=off]:bg-white data-[state=off]:text-[#3D3D3D] data-[state=on]:border-[#0096C6] data-[state=on]:bg-white data-[state=on]:text-[#005F7E]",
  mint:
    "data-[state=off]:border-[#e1e5e8] data-[state=off]:bg-white data-[state=off]:text-[#4b5563] data-[state=on]:border-[rgba(148,224,248,0.95)] data-[state=on]:bg-white data-[state=on]:text-[#063445]",
  danger:
    "data-[state=off]:border-[#e1e5e8] data-[state=off]:bg-white data-[state=off]:text-[#4b5563] data-[state=on]:border-[rgba(239,68,68,0.34)] data-[state=on]:bg-white data-[state=on]:text-[#9f2c2c]",
  neutral:
    "data-[state=off]:border-[#e1e5e8] data-[state=off]:bg-white data-[state=off]:text-[#4b5563] data-[state=on]:border-[#4b5563] data-[state=on]:bg-white data-[state=on]:text-[#4b5563]"
};

type ToggleGroupItemProps = ComponentProps<typeof ToggleGroupPrimitive.Item> & {
  pill?: boolean;
  size?: "sm" | "md" | "lg";
  tone?: ToggleGroupItemTone;
};

function ToggleGroupItem({
  className = "",
  pill = false,
  size = "md",
  tone = "accent",
  ...props
}: ToggleGroupItemProps) {
  const sizeClassName =
    size === "sm"
      ? "min-h-10 px-3.5 py-2 text-[13px]"
      : size === "lg"
        ? "min-h-[42px] px-[18px] text-[14px]"
        : "min-h-11 px-3 py-2 text-[14px]";
  const radiusClassName = pill ? "rounded-full" : "rounded-[14px]";

  return (
    <ToggleGroupPrimitive.Item
      className={`inline-flex cursor-pointer items-center justify-center border font-semibold leading-none transition-colors data-[state=on]:border-2 ${radiusClassName} ${toneClassName[tone]} focus-visible:outline-none focus-visible:shadow-[0_0_0_3px_rgba(148,224,248,0.35)] ${sizeClassName} ${className}`}
      {...props}
    />
  );
}

// 밑줄 탭 스타일(정렬/필터용). 칩 스타일 ToggleGroupItem과 시각 언어가 완전히 달라서 별도 export로 분리했다.
function ToggleGroupTabItem({
  className = "",
  ...props
}: ComponentProps<typeof ToggleGroupPrimitive.Item>) {
  return (
    <ToggleGroupPrimitive.Item
      className={`inline-flex min-h-[54px] cursor-pointer items-center justify-center border-0 border-b-[3px] border-transparent bg-transparent text-[16px] font-extrabold text-[#777777] transition-colors data-[state=on]:border-[#94E0F8] data-[state=on]:text-[#063445] focus-visible:outline-none ${className}`}
      {...props}
    />
  );
}

export { ToggleGroup, ToggleGroupItem, ToggleGroupTabItem };
