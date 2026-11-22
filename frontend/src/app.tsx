/**
 * Application wiring, shared by `main.tsx` and the tests so both run the same setup:
 * API client, query cache (with the global "session ended" handler) and router.
 */
import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type RouterHistory, RouterProvider } from "@tanstack/react-router";
import { ApiClient, isApiError } from "@/api/client";
import { queryKeys } from "@/api/queries";
import type { AppConfig } from "@/config";
import { ListMemory } from "@/lib/listMemory";
import { buildRouter } from "@/router";
import { registerBuiltinWidgets } from "@/widgets/builtin";
import { WidgetRegistry } from "@/widgets/registry";

export interface AppOptions {
  /** Defaults to the browser history; tests pass a memory history. */
  history?: RouterHistory;
}

export function createApp(config: AppConfig, options: AppOptions = {}) {
  const client = new ApiClient(config.apiBase);

  const queryClient: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      // A 401 from any query means the session ended (expiry, sign-out elsewhere, password
      // change): forget it and go to the login page, returning here afterwards.
      onError: (error, query) => {
        if (!isApiError(error, 401) || query.queryKey[0] === queryKeys.session[0]) return;
        client.setCsrfToken(null);
        queryClient.setQueryData(queryKeys.session, null);
        if (config.auth === "builtin") {
          void router.navigate({ to: "/login", search: { next: router.state.location.href } });
        }
      },
    }),
    defaultOptions: {
      queries: {
        // 4xx answers won't change on retry; network failures and 5xx might.
        retry: (failures, error) =>
          failures < 2 && !(isApiError(error) && isClientError(error.status)),
        refetchOnWindowFocus: false,
      },
    },
  });

  const router = buildRouter(
    {
      config,
      client,
      queryClient,
      listMemory: new ListMemory(),
      widgets: registerBuiltinWidgets(new WidgetRegistry()),
    },
    options.history,
  );

  return { client, queryClient, router };
}

export type OneAdminApp = ReturnType<typeof createApp>;

export function App({ app }: { app: OneAdminApp }) {
  return (
    <QueryClientProvider client={app.queryClient}>
      <RouterProvider router={app.router} />
    </QueryClientProvider>
  );
}

function isClientError(status: number): boolean {
  return status >= 400 && status < 500;
}
