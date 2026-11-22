import type { ListSearch } from "./listSearch";

/**
 * The last view (sort, filters, page) of each model's list, so "back to Posts" from a detail
 * page lands where the user left. Lives in the router context, not in a module global, so two
 * admin apps on one page (or two tests) never share it.
 */
export class ListMemory {
  private readonly views = new Map<string, ListSearch>();

  remember(slug: string, search: ListSearch): void {
    this.views.set(slug, search);
  }

  recall(slug: string): ListSearch {
    return this.views.get(slug) ?? {};
  }
}
