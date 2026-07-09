import { type ButtonHTMLAttributes, forwardRef } from "react";

type ButtonVariant = "solid" | "outline" | "link" | "icon";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
};

const variantClassName: Record<ButtonVariant, string> = {
  solid:
    "rounded-[14px] bg-[#0C1117] py-3.5 text-[15px] font-semibold text-white shadow-[0_2px_24px_rgba(0,0,0,0.06)] hover:bg-[#1A1A1A]",
  outline:
    "rounded-[14px] border border-black/[0.07] bg-white py-3 text-[14px] font-semibold text-[#1A1A1A] hover:bg-[#FAFAFA]",
  link: "border-0 bg-transparent text-[13px] font-semibold text-[#6B7280] hover:text-[#1A1A1A]",
  icon: "flex h-11 w-11 items-center justify-center rounded-full border border-black/[0.07] bg-white p-0 hover:bg-[#FAFAFA]"
};

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className = "", variant = "solid", type = "button", ...props },
  ref
) {
  return (
    <button
      className={`cursor-pointer ${variantClassName[variant]} ${className}`}
      ref={ref}
      type={type}
      {...props}
    />
  );
});

export { Button };
