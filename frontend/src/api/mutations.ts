/**
 * Writes (ADR-0018). Every successful write invalidates everything cached about the model,
 * so lists, counts, detail and history refetch. Failures are `ApiError`s; forms read
 * `error.fields` (per-field messages) and `error.current` (the row after a conflict).
 */
import type { QueryClient } from "@tanstack/react-query";
import type { ApiClient } from "./client";
import { queryKeys, rowPath } from "./queries";
import type { ActionOut, RowOut } from "./types";

export async function invalidateModel(queryClient: QueryClient, slug: string): Promise<void> {
  await Promise.all(
    queryKeys.model(slug).map((queryKey) => queryClient.invalidateQueries({ queryKey })),
  );
}

export async function createRow(
  client: ApiClient,
  queryClient: QueryClient,
  slug: string,
  body: Record<string, unknown>,
): Promise<RowOut> {
  const row = await client.post<RowOut>(rowPath(slug), body);
  await invalidateModel(queryClient, slug);
  queryClient.setQueryData(queryKeys.row(slug, row.pk), row);
  return row;
}

export async function updateRow(
  client: ApiClient,
  queryClient: QueryClient,
  slug: string,
  pk: string,
  version: string,
  body: Record<string, unknown>,
): Promise<RowOut> {
  const row = await client.patch<RowOut>(rowPath(slug, pk), body, version);
  await invalidateModel(queryClient, slug);
  queryClient.setQueryData(queryKeys.row(slug, row.pk), row);
  return row;
}

export async function deleteRow(
  client: ApiClient,
  queryClient: QueryClient,
  slug: string,
  pk: string,
  version: string,
): Promise<void> {
  await client.delete(rowPath(slug, pk), version);
  queryClient.removeQueries({ queryKey: queryKeys.row(slug, pk) });
  await invalidateModel(queryClient, slug);
}

export async function runAction(
  client: ApiClient,
  queryClient: QueryClient,
  slug: string,
  action: string,
  pks: string[],
): Promise<ActionOut> {
  const result = await client.post<ActionOut>(
    `/models/${encodeURIComponent(slug)}/actions/${encodeURIComponent(action)}`,
    { pks },
  );
  await invalidateModel(queryClient, slug);
  return result;
}
