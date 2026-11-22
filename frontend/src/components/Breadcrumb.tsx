import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import type { ModelSchema } from "@/api/types";
import { useApp } from "@/lib/app";

/** List and optional record links return to the user's current place in the data workspace. */
export function Breadcrumb({
  model,
  children,
  record,
}: {
  model: ModelSchema;
  children: ReactNode;
  record?: { pk: string; label: string } | undefined;
}) {
  const { listMemory } = useApp();
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex items-center gap-1 text-muted text-xs">
        <li>
          <Link
            to="/m/$slug"
            params={{ slug: model.slug }}
            search={listMemory.recall(model.slug)}
            className="hover:text-fg hover:underline"
          >
            {model.name_plural}
          </Link>
        </li>
        <li aria-hidden="true">
          <ChevronRight className="size-3" />
        </li>
        {record ? (
          <>
            <li className="truncate">
              <Link
                to="/m/$slug/r/$pk"
                params={{ slug: model.slug, pk: record.pk }}
                className="hover:text-fg hover:underline"
              >
                {record.label}
              </Link>
            </li>
            <li aria-hidden="true">
              <ChevronRight className="size-3" />
            </li>
          </>
        ) : null}
        <li aria-current="page" className="truncate">
          {children}
        </li>
      </ol>
    </nav>
  );
}
