/**
 * Small, styled primitives shared by every page. Kept deliberately few: buttons, inputs and
 * status blocks. Interactive overlays (dialogs, popovers) come from Radix.
 */
import type { ComponentProps, ReactNode } from "react";
import { cx } from "@/lib/app";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-accent-fg hover:bg-accent-hover border-transparent",
  secondary: "bg-surface text-fg border-border hover:bg-surface-muted",
  ghost: "bg-transparent text-fg border-transparent hover:bg-surface-muted",
  danger: "bg-danger text-accent-fg border-transparent hover:opacity-90",
};

export const buttonClass = (variant: Variant = "secondary", extra?: string) =>
  cx(
    "inline-flex h-8 items-center justify-center gap-1.5 rounded-[5px] border px-3 text-sm font-medium",
    "transition-colors disabled:pointer-events-none disabled:opacity-50 whitespace-nowrap",
    VARIANTS[variant],
    extra,
  );

interface ButtonProps extends ComponentProps<"button"> {
  variant?: Variant;
}

/** A button that defaults to `type="button"`, so it never submits a form by accident. */
export function Button({
  variant = "secondary",
  className,
  type = "button",
  ...props
}: ButtonProps) {
  return <button type={type} className={buttonClass(variant, className)} {...props} />;
}

export const inputClass = cx(
  "h-8 w-full rounded-[5px] border border-border bg-surface px-3 text-sm text-fg",
  "placeholder:text-muted focus-visible:outline-2 focus-visible:outline-offset-0",
  "aria-invalid:border-danger",
);

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input className={cx(inputClass, className)} {...props} />;
}

export function Select({ className, ...props }: ComponentProps<"select">) {
  return <select className={cx(inputClass, "pr-7", className)} {...props} />;
}

/** Visually hidden text for screen readers. */
export function SrOnly({ children }: { children: ReactNode }) {
  return <span className="sr-only">{children}</span>;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-muted">
      <span
        aria-hidden="true"
        className="size-4 animate-spin rounded-full border-2 border-border border-t-accent"
      />
      <SrOnly>{label}</SrOnly>
    </span>
  );
}

interface NoticeProps {
  tone?: "danger" | "neutral";
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}

/** A block-level message: errors, empty states, setup instructions. */
export function Notice({ tone = "neutral", title, children, action }: NoticeProps) {
  return (
    <div
      role={tone === "danger" ? "alert" : undefined}
      className={cx(
        "rounded-lg border p-4",
        tone === "danger" ? "border-danger/40 bg-danger-soft" : "border-border bg-surface",
      )}
    >
      <p className={cx("font-medium", tone === "danger" && "text-danger")}>{title}</p>
      {children ? <div className="mt-1 text-muted">{children}</div> : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}
