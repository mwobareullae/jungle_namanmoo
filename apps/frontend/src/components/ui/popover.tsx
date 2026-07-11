import {
  createContext,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type ReactNode,
  useContext,
  useEffect,
  useRef,
} from "react";

type MutableRef<T> = {
  current: T | null;
};

type PopoverContextValue = {
  contentRef: MutableRef<HTMLDivElement>;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  triggerRef: MutableRef<HTMLButtonElement>;
};

const PopoverContext = createContext<PopoverContextValue | null>(null);

const usePopoverContext = () => {
  const context = useContext(PopoverContext);
  if (!context) {
    throw new Error("Popover components must be used within Popover");
  }
  return context;
};

type PopoverProps = {
  children: ReactNode;
  onOpenChange: (open: boolean) => void;
  open: boolean;
};

function Popover({ children, onOpenChange, open }: PopoverProps) {
  const contentRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (contentRef.current?.contains(target) || triggerRef.current?.contains(target)) {
        return;
      }
      onOpenChange(false);
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onOpenChange(false);
      window.setTimeout(() => triggerRef.current?.focus(), 0);
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onOpenChange, open]);

  return (
    <PopoverContext.Provider value={{ contentRef, onOpenChange, open, triggerRef }}>
      {children}
    </PopoverContext.Provider>
  );
}

type PopoverTriggerProps = ButtonHTMLAttributes<HTMLButtonElement>;

function PopoverTrigger({ children, onClick, ...props }: PopoverTriggerProps) {
  const { onOpenChange, open, triggerRef } = usePopoverContext();

  return (
    <button
      aria-expanded={open}
      aria-haspopup="menu"
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented) {
          onOpenChange(!open);
        }
      }}
      ref={triggerRef}
      type="button"
      {...props}
    >
      {children}
    </button>
  );
}

type PopoverContentProps = HTMLAttributes<HTMLDivElement>;

function PopoverContent({ children, role = "menu", ...props }: PopoverContentProps) {
  const { contentRef, open } = usePopoverContext();

  if (!open) {
    return null;
  }

  return (
    <div ref={contentRef} role={role} {...props}>
      {children}
    </div>
  );
}

export { Popover, PopoverContent, PopoverTrigger };
