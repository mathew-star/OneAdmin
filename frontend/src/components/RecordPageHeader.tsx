import type { ReactNode } from "react";
import type { ModelSchema } from "@/api/types";
import { Breadcrumb } from "./Breadcrumb";

interface RecordPageHeaderProps {
  model: ModelSchema;
  title: string;
  breadcrumb: ReactNode;
  parentRecord?: { pk: string; label: string } | undefined;
  context: string;
  actions?: ReactNode;
}

/** The same record heading for reading, editing, and creating a row. */
export function RecordPageHeader({
  model,
  title,
  breadcrumb,
  parentRecord,
  context,
  actions,
}: RecordPageHeaderProps) {
  return (
    <header className="border-border border-b bg-surface px-5 py-4 md:px-7">
      <Breadcrumb model={model} record={parentRecord}>
        {breadcrumb}
      </Breadcrumb>
      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
            {context} <span className="mx-1 text-border-strong">/</span> {model.slug}
          </p>
          <h1 className="break-words font-display font-semibold text-2xl tracking-tight">
            {title}
          </h1>
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </header>
  );
}
