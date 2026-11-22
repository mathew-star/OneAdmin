/**
 * TanStack Query definitions: one place for every cache key and fetcher, so invalidation
 * and prefetching stay consistent across pages.
 */
import { type QueryClient, queryOptions } from "@tanstack/react-query";
import { type ListSearch, matchSignature, toApiQuery } from "@/lib/listSearch";
import { type ApiClient, isApiError } from "./client";
import type { CountOut, HistoryOut, ListOut, RowOut, SessionOut, SiteSchema } from "./types";

export const queryKeys = {
  session: ["session"] as const,
  schema: ["schema"] as const,
  rows: (slug: string, search: ListSearch) => ["rows", slug, search] as const,
  count: (slug: string, signature: string) => ["count", slug, signature] as const,
  row: (slug: string, pk: string) => ["row", slug, pk] as const,
  history: (slug: string, pk: string) => ["history", slug, pk] as const,
  /** Everything cached about one model: invalidated after any write to it. */
  model: (slug: string) => [
    ["rows", slug],
    ["count", slug],
    ["row", slug],
    ["history", slug],
  ],
};

/** The signed-in admin, or `null`. Also hands the CSRF token to the client. */
export function sessionQuery(client: ApiClient) {
  return queryOptions({
    queryKey: queryKeys.session,
    queryFn: async ({ signal }): Promise<SessionOut | null> => {
      try {
        const session = await client.get<SessionOut>("/auth/session", undefined, signal);
        client.setCsrfToken(session.csrf_token);
        return session;
      } catch (error) {
        if (isApiError(error, 401)) {
          client.setCsrfToken(null);
          return null;
        }
        throw error;
      }
    },
    staleTime: 5 * 60_000,
  });
}

/**
 * The registered models. Changes only when the application is redeployed. The server sends
 * an ETag with `no-cache`, so the browser revalidates cheaply when we refetch.
 */
export function schemaQuery(client: ApiClient) {
  return queryOptions({
    queryKey: queryKeys.schema,
    queryFn: ({ signal }) => client.get<SiteSchema>("/schema", undefined, signal),
    staleTime: 10 * 60_000,
  });
}

/**
 * One page of rows.
 *
 * The count is requested only when the cache has none for this set of matching rows: paging
 * doesn't change the total, so later pages skip the count query entirely. The count is
 * stored under its own key, which also lets "Count exactly" replace it.
 */
export function rowsQuery(
  client: ApiClient,
  queryClient: QueryClient,
  slug: string,
  search: ListSearch,
) {
  return queryOptions({
    queryKey: queryKeys.rows(slug, search),
    queryFn: async ({ signal }) => {
      const countKey = queryKeys.count(slug, matchSignature(search));
      const needCount = queryClient.getQueryData(countKey) === undefined;
      const page = await client.get<ListOut>(
        `/models/${encodeURIComponent(slug)}/rows`,
        toApiQuery(search, { count: needCount ? "true" : "false" }),
        signal,
      );
      if (page.count) queryClient.setQueryData<CountOut>(countKey, page.count);
      return page;
    },
    staleTime: 30_000,
  });
}

/** The cached count for a list view; filled by {@link rowsQuery} or {@link fetchExactCount}. */
export function countQuery(slug: string, search: ListSearch) {
  return queryOptions<CountOut | null>({
    queryKey: queryKeys.count(slug, matchSignature(search)),
    queryFn: () => null, // never fetched directly: see rowsQuery
    enabled: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
}

export async function fetchExactCount(
  client: ApiClient,
  queryClient: QueryClient,
  slug: string,
  search: ListSearch,
): Promise<CountOut> {
  const { cursor: _c, last: _l, sort: _s, ...matching } = search;
  const count = await client.get<CountOut>(
    `/models/${encodeURIComponent(slug)}/count`,
    toApiQuery(matching),
  );
  queryClient.setQueryData(queryKeys.count(slug, matchSignature(search)), count);
  return count;
}

export function rowQuery(client: ApiClient, slug: string, pk: string) {
  return queryOptions({
    queryKey: queryKeys.row(slug, pk),
    queryFn: ({ signal }) =>
      client.get<RowOut>(
        `/models/${encodeURIComponent(slug)}/rows/${encodeURIComponent(pk)}`,
        undefined,
        signal,
      ),
    staleTime: 30_000,
  });
}

export function historyQuery(client: ApiClient, slug: string, pk: string) {
  return queryOptions({
    queryKey: queryKeys.history(slug, pk),
    queryFn: ({ signal }) =>
      client.get<HistoryOut>(`${rowPath(slug, pk)}/history`, undefined, signal),
  });
}

export function rowPath(slug: string, pk?: string): string {
  const base = `/models/${encodeURIComponent(slug)}/rows`;
  return pk === undefined ? base : `${base}/${encodeURIComponent(pk)}`;
}
