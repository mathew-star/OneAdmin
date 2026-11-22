import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronFirst, ChevronLast, ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { countQuery } from "@/api/queries";
import type { ListOut } from "@/api/types";
import { useModel } from "@/lib/app";
import { firstPage, type ListSearch } from "@/lib/listSearch";
import { buttonClass } from "../ui";

interface PagerProps {
  slug: string;
  search: ListSearch;
  page: ListOut;
}

/**
 * Cursor paging: first, previous, next and (in keyset mode) last. There are no page numbers
 * on purpose: jumping to page N needs OFFSET, which gets slower the deeper it goes (ADR-0003).
 */
export function Pager({ slug, search, page }: PagerProps) {
  const atStart = !search.cursor && !search.last;
  const { data: count } = useQuery(countQuery(slug, search));
  const model = useModel(slug);
  const { last: _last, start: _start, ...withoutLast } = search;
  const knownStart = atStart ? 1 : search.start ? Number(search.start) : null;
  const start =
    search.last && count?.exact && count.value !== null
      ? Math.max(1, count.value - page.rows.length + 1)
      : knownStart;
  const nextStart = start === null ? undefined : String(start + page.rows.length);
  const previousStart = start === null ? undefined : String(Math.max(1, start - model.per_page));
  const total = count?.value == null ? null : count.value.toLocaleString();
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-border border-t bg-surface px-4 py-2.5">
      <p className="font-mono text-[11px] text-muted" aria-live="polite" data-testid="page-range">
        {start === null ? (
          <>
            Showing <strong className="font-semibold text-fg tabular">{page.rows.length}</strong>{" "}
            rows
          </>
        ) : (
          <>
            Showing{" "}
            <strong className="font-semibold text-fg tabular">
              {start.toLocaleString()}–{(start + page.rows.length - 1).toLocaleString()}
            </strong>
          </>
        )}
        {total ? (
          <span>
            {" "}
            of{" "}
            <span
              className="tabular"
              title={
                count?.exact
                  ? "Exact total"
                  : count?.method === "estimate"
                    ? "Estimated total"
                    : "At least this many rows"
              }
            >
              {count?.exact ? total : count?.method === "estimate" ? `about ${total}` : `${total}+`}
            </span>{" "}
            rows
          </span>
        ) : null}
      </p>
      <nav aria-label="Pagination" className="flex items-center gap-0.5">
        <PageLink slug={slug} search={atStart ? null : firstPage(search)} label="First page">
          <ChevronFirst className="size-4" aria-hidden="true" />
        </PageLink>
        <PageLink
          slug={slug}
          search={
            page.prev_cursor
              ? {
                  ...withoutLast,
                  cursor: page.prev_cursor,
                  ...(previousStart ? { start: previousStart } : {}),
                }
              : null
          }
          label="Previous page"
        >
          <ChevronLeft className="size-4" aria-hidden="true" />
          <span className="hidden sm:inline">Previous</span>
        </PageLink>
        <PageLink
          slug={slug}
          search={
            page.next_cursor
              ? {
                  ...withoutLast,
                  cursor: page.next_cursor,
                  ...(nextStart ? { start: nextStart } : {}),
                }
              : null
          }
          label="Next page"
        >
          <span className="hidden sm:inline">Next</span>
          <ChevronRight className="size-4" aria-hidden="true" />
        </PageLink>
        {page.pagination === "keyset" ? (
          <PageLink
            slug={slug}
            // No next page means this already is the last one.
            search={page.next_cursor ? { ...firstPage(search), last: "1" } : null}
            label="Last page"
          >
            <ChevronLast className="size-4" aria-hidden="true" />
          </PageLink>
        ) : null}
      </nav>
    </div>
  );
}

interface PageLinkProps {
  slug: string;
  /** `null` renders a disabled control. */
  search: ListSearch | null;
  label: string;
  children: ReactNode;
}

function PageLink({ slug, search, label, children }: PageLinkProps) {
  const className = buttonClass("ghost", "h-7 px-2 font-mono text-[11px]");
  if (!search) {
    return (
      <button type="button" disabled aria-label={label} title={label} className={className}>
        {children}
      </button>
    );
  }
  return (
    <Link
      to="/m/$slug"
      params={{ slug }}
      search={search}
      aria-label={label}
      title={label}
      className={className}
    >
      {children}
    </Link>
  );
}
