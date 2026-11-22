import { Link } from "@tanstack/react-router";
import { ArrowUpRight } from "lucide-react";
import { Notice } from "@/components/ui";
import { useSchema } from "@/lib/app";

export function IndexPage() {
  const { title, models } = useSchema();
  return (
    <div className="min-h-full bg-bg">
      <header className="border-border border-b bg-surface px-5 py-4 md:px-7">
        <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
          {title} / Data
        </p>
        <h1 className="font-display font-semibold text-2xl tracking-tight">Data models</h1>
      </header>
      <div className="max-w-5xl p-4 md:p-6">
        {models.length === 0 ? (
          <Notice title="No models registered">
            Register a model with <code className="font-mono">admin.register(Model)</code> and
            restart the application.
          </Notice>
        ) : (
          <section
            aria-labelledby="collections-heading"
            className="border border-border bg-surface"
          >
            <div className="flex items-center justify-between gap-4 border-border border-b px-4 py-3">
              <h2 id="collections-heading" className="font-semibold text-sm">
                Registered models
              </h2>
              <span className="font-mono text-[11px] text-muted tabular">
                {String(models.length).padStart(2, "0")} total
              </span>
            </div>
            <ul className="divide-y divide-border">
              {models.map((model, index) => (
                <li key={model.slug}>
                  <Link
                    to="/m/$slug"
                    params={{ slug: model.slug }}
                    className="group flex items-center gap-4 px-4 py-4 transition-colors hover:bg-surface-muted"
                  >
                    <span
                      className="w-7 shrink-0 font-mono text-xs text-muted tabular"
                      aria-hidden="true"
                    >
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span className="min-w-0 flex-1 truncate font-medium">{model.name_plural}</span>
                    <span className="hidden font-mono text-[11px] text-muted sm:inline">
                      /{model.slug}
                    </span>
                    <ArrowUpRight
                      className="size-4 text-muted transition-colors group-hover:text-accent"
                      aria-hidden="true"
                    />
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}
