import { useMutation, useQuery } from "@tanstack/react-query";
import { countQuery, fetchExactCount } from "@/api/queries";
import { useApp } from "@/lib/app";
import { formatCount } from "@/lib/format";
import type { ListSearch } from "@/lib/listSearch";
import { Button } from "../ui";

/**
 * The row count for the current filters. Cheap counts (estimated or capped) come with the
 * first page; "Count exactly" asks for the precise number on demand, since an exact count of
 * millions of filtered rows can take seconds (ADR-0004).
 */
export function CountStatus({ slug, search }: { slug: string; search: ListSearch }) {
  const { client, queryClient } = useApp();
  const { data: count } = useQuery(countQuery(slug, search));
  const exact = useMutation({
    mutationFn: () => fetchExactCount(client, queryClient, slug, search),
  });
  const text = count ? formatCount(count) : null;

  return (
    <div className="flex items-center gap-2 font-mono text-[11px] text-muted" aria-live="polite">
      {text ? (
        <span title={text.long} className="tabular">
          {text.short === text.long ? (
            text.short
          ) : (
            <>
              <span aria-hidden="true">{text.short}</span>
              <span className="sr-only">{text.long}</span>
            </>
          )}
        </span>
      ) : null}
      {count && !count.exact ? (
        <Button
          variant="ghost"
          className="h-6 px-1.5 font-sans text-xs text-accent"
          onClick={() => exact.mutate()}
          disabled={exact.isPending}
        >
          {exact.isPending ? "Counting…" : "Count exactly"}
        </Button>
      ) : null}
      {exact.isError ? (
        <span role="alert" className="text-danger">
          {exact.error.message}
        </span>
      ) : null}
    </div>
  );
}
