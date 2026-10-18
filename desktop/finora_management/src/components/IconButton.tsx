import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/utils/cn";

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  children: ReactNode;
  tone?: "default" | "danger";
  size?: "sm" | "md";
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, children, tone = "default", size = "md", className, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      className={cn(
        "no-drag inline-flex items-center justify-center rounded-control text-ink-soft transition-colors duration-150",
        "hover:bg-violet-soft hover:text-violet-deep active:scale-[0.97] disabled:pointer-events-none disabled:opacity-40",
        tone === "danger" && "hover:bg-danger hover:text-white",
        size === "md" ? "h-10 w-10" : "h-8 w-8",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
});
