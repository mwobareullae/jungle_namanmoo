import { type ComponentProps, forwardRef } from "react";

type InputProps = ComponentProps<"input"> & {
  invalid?: boolean;
};

const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className = "", invalid = false, ...props },
  ref
) {
  return (
    <input
      className={`w-full rounded-[14px] border px-4 py-3 text-[15px] text-[#1A1A1A] focus:outline-none ${
        invalid
          ? "border-[#ff2b2b] focus:border-[#ff2b2b]"
          : "border-[rgba(0,0,0,0.07)] focus:border-[rgba(148,224,248,0.44)]"
      } ${className}`}
      ref={ref}
      {...props}
    />
  );
});

export { Input };
