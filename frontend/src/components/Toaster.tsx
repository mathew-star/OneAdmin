/**
 * Short status messages ("Saved", "3 orders marked paid"), announced to screen readers via
 * a polite live region. Lives at the root of the app, so a toast survives the navigation
 * that usually follows a write.
 */
import { X } from "lucide-react";
import { createContext, type ReactNode, use, useCallback, useMemo, useRef, useState } from "react";
import { cx } from "@/lib/app";

type Tone = "success" | "error";

interface Toast {
  id: number;
  message: string;
  tone: Tone;
}

interface ToastApi {
  show: (message: string, tone?: Tone) => void;
}

const ToastContext = createContext<ToastApi | null>(null);
const LIFETIME_MS = 5_000;

export function Toaster({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(0);

  const dismiss = useCallback(
    (id: number) => setToasts((all) => all.filter((t) => t.id !== id)),
    [],
  );
  const show = useCallback(
    (message: string, tone: Tone = "success") => {
      nextId.current += 1;
      const id = nextId.current;
      setToasts((all) => [...all.slice(-2), { id, message, tone }]);
      setTimeout(() => dismiss(id), LIFETIME_MS);
    },
    [dismiss],
  );
  const api = useMemo(() => ({ show }), [show]);

  return (
    <ToastContext value={api}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cx(
              "pointer-events-auto flex items-start gap-2 rounded-lg border bg-surface p-3 shadow-lg",
              toast.tone === "error" ? "border-danger/40 text-danger" : "border-border",
            )}
          >
            <p className="flex-1">{toast.message}</p>
            <button
              type="button"
              onClick={() => dismiss(toast.id)}
              className="rounded p-0.5 text-muted hover:text-fg"
              aria-label="Dismiss"
            >
              <X className="size-4" aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext>
  );
}

export function useToast(): ToastApi {
  const api = use(ToastContext);
  if (!api) throw new Error("useToast must be used inside <Toaster>");
  return api;
}
