import { Link } from "@tanstack/react-router";
import { Check, X } from "lucide-react";
import type { FieldKind, RelationValue } from "@/api/types";
import { cx } from "@/lib/app";
import { display, type FormatOptions } from "@/lib/format";
import { SrOnly } from "./ui";

interface ValueProps extends FormatOptions {
  kind: FieldKind;
  value: unknown;
}

/** One field value, rendered by its kind. */
export function Value({ kind, value, ...options }: ValueProps) {
  const d = display(kind, value, options);
  switch (d.type) {
    case "empty":
      return (
        <span className="text-muted">
          <span aria-hidden="true">—</span>
          <SrOnly>empty</SrOnly>
        </span>
      );
    case "boolean":
      return d.value ? (
        <span className="inline-flex items-center text-success">
          <Check className="size-4" aria-hidden="true" />
          <SrOnly>Yes</SrOnly>
        </span>
      ) : (
        <span className="inline-flex items-center text-muted">
          <X className="size-4" aria-hidden="true" />
          <SrOnly>No</SrOnly>
        </span>
      );
    case "badge":
      return (
        <span className="inline-flex rounded bg-surface-muted px-1.5 py-0.5 text-xs font-medium">
          {d.text}
        </span>
      );
    case "text":
      return (
        <span
          title={d.title}
          className={cx(
            d.mono && "font-mono text-xs",
            d.numeric && "tabular",
            options.full && "whitespace-pre-wrap break-words",
          )}
        >
          {d.text}
        </span>
      );
  }
}

interface RelationLinkProps {
  relation: RelationValue | null;
  /** Slug of the related model's admin; `null` if it isn't registered (no link then). */
  target: string | null;
}

/**
 * A foreign key shown by the related row's label. A `null` label means the related row
 * exists but the viewer's scope doesn't include it: show only that, never its key's data.
 */
export function RelationLink({ relation, target }: RelationLinkProps) {
  if (!relation) return <Value kind="unknown" value={null} />;
  const text = relation.label ?? `#${relation.pk}`;
  if (!target || relation.label === null) {
    return <span className={cx(relation.label === null && "text-muted")}>{text}</span>;
  }
  return (
    <Link
      to="/m/$slug/r/$pk"
      params={{ slug: target, pk: relation.pk }}
      className="text-accent hover:underline"
    >
      {text}
    </Link>
  );
}
