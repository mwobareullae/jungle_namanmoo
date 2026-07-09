import { type ButtonHTMLAttributes, forwardRef } from "react";
import { type ButtonVariant, buttonVariantClassName } from "./button-variants";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
};

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className = "", variant = "solid", type = "button", ...props },
  ref
) {
  return (
    <button
      className={`cursor-pointer ${buttonVariantClassName[variant]} ${className}`}
      ref={ref}
      type={type}
      {...props}
    />
  );
});

export { Button };
