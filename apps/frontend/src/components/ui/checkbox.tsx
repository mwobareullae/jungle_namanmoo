import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import { type ComponentProps } from "react";

function Checkbox({ className = "", ...props }: ComponentProps<typeof CheckboxPrimitive.Root>) {
  return (
    <CheckboxPrimitive.Root
      className={`inline-grid h-4 w-4 shrink-0 cursor-pointer place-content-center rounded-[5px] border border-[#D1D5DB] bg-white transition-colors data-[state=checked]:border-[#94e0f8] data-[state=checked]:bg-[#94e0f8] focus-visible:outline-none focus-visible:shadow-[0_0_0_3px_rgba(148,224,248,0.35)] ${className}`}
      {...props}
    >
      <CheckboxPrimitive.Indicator>
        <svg
          fill="none"
          height="11"
          stroke="#ffffff"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="3.5"
          viewBox="0 0 24 24"
          width="11"
        >
          <path d="M4 12l6 6L20 6" />
        </svg>
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}

export { Checkbox };
