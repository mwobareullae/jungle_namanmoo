export type ButtonVariant = "solid" | "outline" | "link" | "icon";

// button 이외의 요소(Link, a)에 같은 스타일을 입힐 때도 이 맵을 그대로 재사용한다.
// 절대 문자열을 복사-붙여넣기 하지 말 것 — variant 스타일이 바뀌면 여기 하나만 고치면 되게 유지한다.
export const buttonVariantClassName: Record<ButtonVariant, string> = {
  solid:
    "rounded-[14px] bg-[#0C1117] py-3.5 text-[15px] font-semibold text-white shadow-[0_2px_24px_rgba(0,0,0,0.06)] hover:bg-[#1A1A1A]",
  outline:
    "rounded-[14px] border border-black/[0.07] bg-white py-3 text-[14px] font-semibold text-[#1A1A1A] hover:bg-[#FAFAFA]",
  link: "border-0 bg-transparent text-[13px] font-semibold text-[#6B7280] hover:text-[#1A1A1A]",
  icon: "flex h-11 w-11 items-center justify-center rounded-full border border-black/[0.07] bg-white p-0 hover:bg-[#FAFAFA]"
};
