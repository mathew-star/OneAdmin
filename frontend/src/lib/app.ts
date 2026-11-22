/** Hooks to reach the app-wide services held in the router context. */
import { useSuspenseQuery } from "@tanstack/react-query";
import { notFound, useRouteContext } from "@tanstack/react-router";
import { schemaQuery } from "@/api/queries";
import type { ModelSchema, SiteSchema } from "@/api/types";
import type { RouterContext } from "@/router";

export function useApp(): RouterContext {
  return useRouteContext({ from: "__root__" });
}

/** The site schema. Always loaded: the `app` route's loader fetches it before rendering. */
export function useSchema(): SiteSchema {
  const { client } = useApp();
  return useSuspenseQuery(schemaQuery(client)).data;
}

/** The schema of model `slug`, or the not-found page if no such model is registered. */
export function useModel(slug: string): ModelSchema {
  const model = useSchema().models.find((m) => m.slug === slug);
  if (!model) throw notFound();
  return model;
}

/** Join class names, skipping falsy ones: `cx("a", cond && "b")`. */
export function cx(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}
