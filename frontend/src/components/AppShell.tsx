/**
 * The signed-in layout: a sidebar with the model navigation (a slide-over dialog on narrow
 * screens) and the routed page.
 */
import { Link, Outlet } from "@tanstack/react-router";
import { Menu, X } from "lucide-react";
import { Dialog } from "radix-ui";
import { useState } from "react";
import { useApp, useSchema } from "@/lib/app";
import { DevBadge } from "@/pages/LoginPage";
import { UserMenu } from "./UserMenu";
import { Button } from "./ui";

export function AppShell() {
  const { title } = useSchema();
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className="flex h-full bg-bg">
      <SkipLink />
      <aside className="hidden w-56 shrink-0 flex-col border-border border-r bg-surface md:flex">
        <Sidebar title={title} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center gap-2 border-border border-b bg-surface px-3 md:hidden">
          <Dialog.Root open={navOpen} onOpenChange={setNavOpen}>
            <Dialog.Trigger asChild>
              <Button variant="ghost" className="px-2" aria-label="Open navigation">
                <Menu className="size-4" aria-hidden="true" />
              </Button>
            </Dialog.Trigger>
            <Dialog.Portal>
              <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
              <Dialog.Content className="fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col bg-surface shadow-xl">
                <Dialog.Title className="sr-only">Navigation</Dialog.Title>
                <Dialog.Description className="sr-only">Registered models</Dialog.Description>
                <Dialog.Close asChild>
                  <Button
                    variant="ghost"
                    className="absolute top-2 right-2 px-2"
                    aria-label="Close navigation"
                  >
                    <X className="size-4" aria-hidden="true" />
                  </Button>
                </Dialog.Close>
                <Sidebar title={title} onNavigate={() => setNavOpen(false)} />
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>
          <span className="truncate font-semibold">{title}</span>
        </header>

        <main id="main" tabIndex={-1} className="min-w-0 flex-1 overflow-auto focus:outline-none">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

interface SidebarProps {
  title: string;
  /** Called when a link is followed (closes the mobile navigation dialog). */
  onNavigate?: () => void;
}

function Sidebar({ title, onNavigate }: SidebarProps) {
  const { config } = useApp();
  const { models } = useSchema();
  return (
    <>
      <Link
        to="/"
        onClick={onNavigate}
        className="flex min-h-16 items-center gap-3 border-border border-b px-4"
      >
        <span
          className="flex size-8 shrink-0 items-center justify-center rounded-md bg-accent font-mono font-bold text-accent-fg text-xs"
          aria-hidden="true"
        >
          1/
        </span>
        <span className="min-w-0">
          <span className="block truncate font-semibold leading-tight">{title}</span>
          <span className="block font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
            OneAdmin
          </span>
        </span>
        {config.dev ? <DevBadge /> : null}
      </Link>
      <nav aria-label="Models" className="flex-1 overflow-y-auto px-2 py-5">
        <p className="mb-3 px-3 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-muted">
          Data models
        </p>
        <ul className="space-y-0.5">
          {models.map((model, index) => (
            <li key={model.slug}>
              <Link
                to="/m/$slug"
                params={{ slug: model.slug }}
                onClick={onNavigate}
                className="flex items-center gap-2.5 rounded-md border-l-2 border-transparent px-2.5 py-2 font-medium text-fg transition-colors hover:bg-surface-muted"
                activeProps={{
                  className:
                    "border-accent bg-accent-soft font-semibold text-fg hover:bg-accent-soft",
                  "aria-current": "page",
                }}
                activeOptions={{ includeSearch: false }}
              >
                <span
                  className="w-5 shrink-0 font-mono text-[10px] text-fg tabular"
                  aria-hidden="true"
                >
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="truncate">{model.name_plural}</span>
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <UserMenu />
    </>
  );
}

/**
 * "Skip to content". A button rather than `<a href="#main">`: a fragment link resolves
 * against the injected `<base href>` and would navigate away from the current page.
 */
function SkipLink() {
  return (
    <button
      type="button"
      onClick={() => document.getElementById("main")?.focus()}
      className="sr-only z-50 rounded-md bg-surface px-3 py-2 shadow focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
    >
      Skip to content
    </button>
  );
}
