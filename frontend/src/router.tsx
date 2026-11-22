/**
 * Route tree (code-based, so there's no generated route file to keep in sync).
 *
 *   /login               sign in (built-in auth only)
 *   /                    model index
 *   /m/$slug             list
 *   /m/$slug/r/$pk       detail
 *
 * Everything except /login sits under the `app` layout route, whose `beforeLoad` is the
 * single authentication gate.
 */
import type { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  lazyRouteComponent,
  notFound,
  Outlet,
  type RouterHistory,
  redirect,
} from "@tanstack/react-router";
import type { ApiClient } from "@/api/client";
import { schemaQuery, sessionQuery } from "@/api/queries";
import { AppShell } from "@/components/AppShell";
import { RouteError } from "@/components/RouteError";
import { Toaster } from "@/components/Toaster";
import type { AppConfig } from "@/config";
import type { ListMemory } from "@/lib/listMemory";
import { parseListSearch } from "@/lib/listSearch";
import { safeNext } from "@/lib/safeNext";
import { parseSearch, stringifySearch } from "@/lib/searchParams";
import { DetailPage } from "@/pages/DetailPage";
import { IndexPage } from "@/pages/IndexPage";
import { ListPage } from "@/pages/ListPage";
import { LoginPage } from "@/pages/LoginPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import type { WidgetRegistry } from "@/widgets/registry";

export interface RouterContext {
  config: AppConfig;
  client: ApiClient;
  queryClient: QueryClient;
  /** Remembers each list's last view so breadcrumbs return to it. */
  listMemory: ListMemory;
  /** Cells and inputs by widget key (built-ins registered by `createApp`). */
  widgets: WidgetRegistry;
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: () => (
    <Toaster>
      <Outlet />
    </Toaster>
  ),
  notFoundComponent: NotFoundPage,
});

export const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  validateSearch: (raw: Record<string, unknown>): { next?: string } =>
    typeof raw.next === "string" ? { next: safeNext(raw.next) } : {},
  beforeLoad: async ({ context, search }) => {
    if (context.config.auth !== "builtin") throw redirect({ to: "/" });
    const session = await context.queryClient.ensureQueryData(sessionQuery(context.client));
    if (session) throw redirect({ href: safeNext(search.next) });
  },
  component: LoginPage,
});

export const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "app",
  beforeLoad: async ({ context, location }) => {
    if (context.config.auth === "builtin") {
      const session = await context.queryClient.ensureQueryData(sessionQuery(context.client));
      if (!session) throw redirect({ to: "/login", search: { next: location.href } });
      return { session };
    }
    return { session: null };
  },
  loader: ({ context }) => context.queryClient.ensureQueryData(schemaQuery(context.client)),
  component: AppShell,
  errorComponent: RouteError,
  notFoundComponent: NotFoundPage,
});

/** Model routes 404 (inside the shell) when no admin is registered under `slug`. */
async function requireModel(context: RouterContext, slug: string): Promise<void> {
  const schema = await context.queryClient.ensureQueryData(schemaQuery(context.client));
  if (!schema.models.some((m) => m.slug === slug)) throw notFound();
}

export const indexRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/",
  component: IndexPage,
});

export const listRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/m/$slug",
  validateSearch: parseListSearch,
  loader: ({ context, params }) => requireModel(context, params.slug),
  component: ListPage,
  errorComponent: RouteError,
});

export const createRowRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/m/$slug/new",
  loader: ({ context, params }) => requireModel(context, params.slug),
  // Editing screens are separate chunks: they don't count against the initial bundle.
  component: lazyRouteComponent(() => import("@/pages/CreatePage"), "CreatePage"),
  errorComponent: RouteError,
});

export const editRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/m/$slug/r/$pk/edit",
  loader: ({ context, params }) => requireModel(context, params.slug),
  component: lazyRouteComponent(() => import("@/pages/EditPage"), "EditPage"),
  errorComponent: RouteError,
});

export const detailRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/m/$slug/r/$pk",
  loader: ({ context, params }) => requireModel(context, params.slug),
  component: DetailPage,
  errorComponent: RouteError,
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  appRoute.addChildren([indexRoute, listRoute, createRowRoute, detailRoute, editRoute]),
]);

export function buildRouter(context: RouterContext, history?: RouterHistory) {
  return createRouter({
    routeTree,
    context,
    ...(history ? { history } : {}),
    basepath: context.config.basePath,
    // Flat `key=value` query strings with string values, matching the API's parameters.
    parseSearch,
    stringifySearch,
    defaultPreload: "intent",
    // Data freshness is TanStack Query's job; the router shouldn't cache loader results too.
    defaultPreloadStaleTime: 0,
    scrollRestoration: true,
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof buildRouter>;
  }
}
