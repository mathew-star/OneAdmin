import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { isApiError } from "@/api/client";
import { rowsQuery } from "@/api/queries";
import { ActionBar } from "@/components/list/ActionBar";
import { CountStatus } from "@/components/list/CountStatus";
import { DataTable, type Selection } from "@/components/list/DataTable";
import { FilterBar } from "@/components/list/FilterBar";
import { Pager } from "@/components/list/Pager";
import { SearchBox } from "@/components/list/SearchBox";
import { buttonClass, Notice, Spinner } from "@/components/ui";
import { useApp, useModel } from "@/lib/app";
import { listColumns } from "@/lib/columns";
import { activeFilters, type ListSearch, withSearch } from "@/lib/listSearch";

export function ListPage() {
  const { slug } = useParams({ from: "/app/m/$slug" });
  const search = useSearch({ from: "/app/m/$slug" });
  const model = useModel(slug);
  const { client, queryClient, listMemory } = useApp();
  const navigate = useNavigate({ from: "/m/$slug" });
  const columns = useMemo(() => listColumns(model), [model]);

  useEffect(() => listMemory.remember(slug, search), [listMemory, slug, search]);

  const rows = useQuery({
    ...rowsQuery(client, queryClient, slug, search),
    // Keep showing the current page while the next one loads (no flash of empty table)...
    placeholderData: (previous, previousQuery) =>
      // ...but never another model's rows.
      previousQuery?.queryKey[1] === slug ? keepPreviousData(previous) : undefined,
  });

  const go = (next: ListSearch) => navigate({ search: next });
  const narrowed = Boolean(search.q) || activeFilters(search).length > 0;

  // The selection belongs to one view: changing the page, sort or filters starts afresh.
  const viewKey = `${slug}?${JSON.stringify(search)}`;
  const [picked, setPicked] = useState<{ view: string; pks: ReadonlySet<string> }>({
    view: "",
    pks: new Set(),
  });
  const selected = picked.view === viewKey ? picked.pks : NOTHING;
  const pageRows = rows.data?.rows ?? [];
  const selection: Selection | undefined =
    model.actions.length > 0
      ? {
          selected,
          toggle: (pk) => setPicked({ view: viewKey, pks: toggled(selected, pk) }),
          togglePage: () => {
            const all = pageRows.length > 0 && pageRows.every((r) => selected.has(r.pk));
            setPicked({ view: viewKey, pks: all ? NOTHING : new Set(pageRows.map((r) => r.pk)) });
          },
        }
      : undefined;

  return (
    <div className="min-h-full bg-bg">
      <header className="flex flex-wrap items-center justify-between gap-3 border-border border-b bg-surface px-5 py-4 md:px-7">
        <div className="min-w-0">
          <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
            Data <span className="mx-1 text-border-strong">/</span> {model.name_plural}
          </p>
          <h1 className="truncate font-display font-semibold text-2xl tracking-tight">
            {model.name_plural}
          </h1>
        </div>
        {model.permissions.add ? (
          <Link
            to="/m/$slug/new"
            params={{ slug }}
            className={buttonClass("primary", "shadow-none")}
          >
            <Plus className="size-4" aria-hidden="true" />
            Add {model.name.toLowerCase()}
          </Link>
        ) : null}
      </header>

      <div className="p-4 md:p-6">
        <div className="border border-border bg-surface">
          <div className="flex flex-wrap items-center justify-between gap-3 border-border border-b px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              {model.searchable ? (
                <SearchBox
                  value={search.q ?? ""}
                  label={`Search ${model.name_plural}`}
                  onCommit={(q) => void navigate({ search: withSearch(search, q), replace: true })}
                />
              ) : null}
              <FilterBar model={model} search={search} onApply={go} />
            </div>
            <CountStatus slug={slug} search={search} />
          </div>

          {selected.size > 0 ? (
            <ActionBar
              model={model}
              selected={[...selected]}
              onDone={() => setPicked({ view: viewKey, pks: NOTHING })}
            />
          ) : null}

          {rows.isError ? (
            <ListError error={rows.error} slug={slug} />
          ) : rows.data === undefined ? (
            <div className="py-12 text-center">
              <Spinner label={`Loading ${model.name_plural}`} />
            </div>
          ) : rows.data.rows.length === 0 ? (
            <Notice
              title={
                narrowed
                  ? `No ${model.name_plural.toLowerCase()} match`
                  : `No ${model.name_plural.toLowerCase()} yet`
              }
              action={
                narrowed ? (
                  <Link
                    to="/m/$slug"
                    params={{ slug }}
                    search={{}}
                    className="text-accent hover:underline"
                  >
                    Clear search and filters
                  </Link>
                ) : null
              }
            />
          ) : (
            <div>
              <DataTable
                model={model}
                columns={columns}
                rows={rows.data.rows}
                search={search}
                stale={rows.isPlaceholderData}
                selection={selection}
              />
              {rows.isPlaceholderData ? (
                <div className="border-border border-t px-5 py-3 text-muted text-sm" role="status">
                  Loading page…
                </div>
              ) : (
                <Pager slug={slug} search={search} page={rows.data} />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** Invalid view parameters (a stale bookmark, an expired cursor) get a way back. */
function ListError({ error, slug }: { error: Error; slug: string }) {
  if (isApiError(error, 400)) {
    return (
      <Notice
        tone="danger"
        title="This view can't be shown"
        action={
          <Link to="/m/$slug" params={{ slug }} search={{}} className="text-accent hover:underline">
            Reset the view
          </Link>
        }
      >
        {error.message}
      </Notice>
    );
  }
  throw error; // anything else is for the route's error boundary
}

const NOTHING: ReadonlySet<string> = new Set();

function toggled(set: ReadonlySet<string>, pk: string): ReadonlySet<string> {
  const next = new Set(set);
  if (!next.delete(pk)) next.add(pk);
  return next;
}
