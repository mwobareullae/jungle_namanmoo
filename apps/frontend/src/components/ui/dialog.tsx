import * as DialogPrimitive from "@radix-ui/react-dialog";
import { type ComponentProps } from "react";

function Dialog(props: ComponentProps<typeof DialogPrimitive.Root>) {
  return <DialogPrimitive.Root {...props} />;
}

function DialogOverlay(props: ComponentProps<typeof DialogPrimitive.Overlay>) {
  return <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60" {...props} />;
}

function DialogContent({
  children,
  className = "",
  ...props
}: ComponentProps<typeof DialogPrimitive.Content>) {
  return (
    <DialogPrimitive.Portal>
      <DialogOverlay />
      <DialogPrimitive.Content
        className={`fixed left-1/2 top-1/2 z-50 flex max-h-[82vh] w-[calc(100%-2.5rem)] max-w-[560px] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-[20px] border border-black/[0.07] bg-white shadow-[0_24px_80px_rgba(0,0,0,0.24)] focus:outline-none ${className}`}
        {...props}
      >
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

function DialogHeader({ className = "", ...props }: ComponentProps<"div">) {
  return (
    <div
      className={`flex items-start justify-between gap-4 px-6 pt-6 pb-4 sm:px-8 sm:pt-8 ${className}`}
      {...props}
    />
  );
}

function DialogTitle(props: ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      className="text-[24px] font-semibold leading-[1.3] text-[#1A1A1A]"
      {...props}
    />
  );
}

function DialogCloseButton(props: ComponentProps<typeof DialogPrimitive.Close>) {
  return (
    <DialogPrimitive.Close
      aria-label="닫기"
      className="cursor-pointer border-0 bg-transparent text-[28px] leading-none text-[#6B7280] hover:text-[#1A1A1A]"
      {...props}
    >
      ×
    </DialogPrimitive.Close>
  );
}

function DialogBody({ className = "", ...props }: ComponentProps<"div">) {
  return (
    <div
      className={`min-h-0 flex-1 overflow-y-auto border-y border-black/[0.07] px-6 py-5 sm:px-8 ${className}`}
      {...props}
    />
  );
}

function DialogFooter({ className = "", ...props }: ComponentProps<"div">) {
  return <div className={`px-6 py-4 sm:px-8 ${className}`} {...props} />;
}

export {
  Dialog,
  DialogBody,
  DialogCloseButton,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
};
