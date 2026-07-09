import * as ToggleGroupPrimitive from "@radix-ui/react-toggle-group";
import { type ComponentProps } from "react";

function ToggleGroup(props: ComponentProps<typeof ToggleGroupPrimitive.Root>) {
  return <ToggleGroupPrimitive.Root {...props} />;
}

type ToggleGroupItemProps = ComponentProps<typeof ToggleGroupPrimitive.Item> & {
  size?: "sm" | "md";
};

function ToggleGroupItem({ className = "", size = "md", ...props }: ToggleGroupItemProps) {
  const sizeClassName =
    size === "sm" ? "min-h-10 px-3.5 py-2 text-[13px]" : "min-h-11 px-3 py-2 text-[14px]";

  return (
    <ToggleGroupPrimitive.Item
      className={`cursor-pointer rounded-[14px] border font-semibold transition-colors data-[state=off]:border-[rgba(0,0,0,0.07)] data-[state=off]:bg-white data-[state=off]:text-[#3D3D3D] data-[state=on]:border-[#0096C6] data-[state=on]:bg-[rgba(0,150,198,0.12)] data-[state=on]:text-[#005F7E] focus-visible:outline-none focus-visible:shadow-[0_0_0_3px_rgba(148,224,248,0.35)] ${sizeClassName} ${className}`}
      {...props}
    />
  );
}

export { ToggleGroup, ToggleGroupItem };
