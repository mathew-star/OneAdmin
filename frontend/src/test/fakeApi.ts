/**
 * An in-memory stand-in for the admin API, for tests that render the whole app.
 *
 * It follows the real contract's shapes (typed from the generated OpenAPI types) and its
 * write rules where the UI depends on them: `If-Match` versions (428/409 with `current`),
 * per-field `validation_failed`, actions and history. It records every request.
 */
import { vi } from "vitest";
import type {
  FieldSchema,
  HistoryEntry,
  ListOut,
  ModelPermissions,
  ModelSchema,
  RowOut,
  SessionOut,
  SiteSchema,
} from "@/api/types";

export function field(overrides: Partial<FieldSchema> & Pick<FieldSchema, "name">): FieldSchema {
  return {
    label: overrides.name.charAt(0).toUpperCase() + overrides.name.slice(1).replace(/_/g, " "),
    kind: "string",
    nullable: false,
    primary_key: false,
    sortable: true,
    filter_ops: [],
    enum_values: null,
    max_length: null,
    tz_aware: false,
    writable: false,
    required: false,
    ...overrides,
    widget: overrides.widget ?? overrides.kind ?? "string",
  };
}

const ALL: ModelPermissions = { view: true, add: true, change: true, delete: true };
export const VIEW_ONLY: ModelPermissions = { view: true, add: false, change: false, delete: false };

export const usersModel: ModelSchema = {
  slug: "users",
  name: "User",
  name_plural: "Users",
  pk: ["id"],
  label_field: "email",
  fields: [
    field({ name: "id", kind: "integer", primary_key: true }),
    field({ name: "email", filter_ops: ["eq"], writable: true, required: true, widget: "email" }),
  ],
  relations: [],
  list_display: ["id", "email"],
  list_filter: [],
  searchable: true,
  default_sort: ["id"],
  per_page: 50,
  permissions: VIEW_ONLY,
  actions: [],
};

export function postsModel(permissions: ModelPermissions = ALL): ModelSchema {
  const canChange = permissions.change;
  return {
    slug: "posts",
    name: "Post",
    name_plural: "Posts",
    pk: ["id"],
    label_field: "title",
    fields: [
      field({ name: "id", kind: "integer", primary_key: true }),
      field({
        name: "title",
        filter_ops: ["icontains"],
        writable: true,
        required: true,
        max_length: 200,
      }),
      field({ name: "published", kind: "boolean", filter_ops: ["eq"], writable: true }),
      field({
        name: "author_id",
        label: "Author id",
        kind: "integer",
        writable: true,
        required: true,
      }),
    ],
    relations: [{ name: "author", label: "Author", local_field: "author_id", target: "users" }],
    list_display: ["id", "title", "author", "published"],
    list_filter: ["published"],
    searchable: true,
    default_sort: ["-id"],
    per_page: 2,
    permissions,
    actions: canChange
      ? [
          {
            name: "delete_selected",
            label: "Delete selected",
            confirm: "Delete them?",
            destructive: true,
          },
          { name: "publish", label: "Publish", confirm: null, destructive: false },
        ]
      : [],
  };
}

const USERS: RowOut[] = [
  { pk: "1", values: { id: 1, email: "ada@example.com" } },
  { pk: "2", values: { id: 2, email: "bob@example.com" } },
];

interface Post {
  id: number;
  title: string;
  published: boolean;
  author_id: number | null;
  version: number;
}

const session: SessionOut = {
  user: { id: "1", email: "root@example.com", is_superuser: true },
  csrf_token: "csrf-1",
};

export interface FakeApi {
  fetch: ReturnType<typeof vi.fn>;
  signedIn: boolean;
  /** Requests as `METHOD path?query`, in order. */
  log: string[];
  posts: Post[];
  history: HistoryEntry[];
  /** Simulate another admin's edit (bumps the version). */
  editElsewhere: (id: number, changes: Partial<Post>) => void;
  /** Make the next write fail with these field errors. */
  failNextWith: Record<string, string> | null;
  /** Dev-mode first-run setup is available (no admin user yet). */
  setupNeeded: boolean;
}

export function installFakeApi({ signedIn = true, permissions = ALL } = {}): FakeApi {
  const posts: Post[] = [
    { id: 3, title: "Third", published: true, author_id: 1, version: 1 },
    { id: 2, title: "Second", published: false, author_id: 9, version: 1 },
    { id: 1, title: "First", published: true, author_id: null, version: 1 },
  ];
  const schema: SiteSchema = {
    contract_version: 1,
    title: "Test Site",
    models: [postsModel(permissions), usersModel],
  };
  const api: FakeApi = {
    fetch: vi.fn(),
    signedIn,
    log: [],
    posts,
    history: [],
    failNextWith: null,
    setupNeeded: false,
    editElsewhere: (id, changes) => {
      const post = posts.find((p) => p.id === id);
      if (post) Object.assign(post, changes, { version: post.version + 1 });
    },
  };
  let nextId = 4;
  let nextAudit = 1;

  const json = (status: number, body: unknown) =>
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  const problem = (status: number, code: string, message: string, extra: object = {}) =>
    json(status, { error: { code, message, param: null, ...extra } });

  const audit = (action: string, changes: Record<string, unknown[]>) =>
    api.history.unshift({
      id: nextAudit++,
      at: "2026-11-06T12:00:00Z",
      actor_id: "1",
      actor_email: session.user.email,
      action,
      changes,
    });

  api.fetch.mockImplementation(async (input: string, init: RequestInit = {}) => {
    const url = new URL(input, "https://test");
    const method = init.method ?? "GET";
    const path = url.pathname.replace(/^\/admin\/api\/v1/, "");
    const headers = (init.headers ?? {}) as Record<string, string>;
    const body = init.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    api.log.push(`${method} ${path}${url.search}`);

    if (path === "/auth/login" && method === "POST") {
      if (body.password !== "right password") {
        return problem(401, "invalid_credentials", "Invalid email or password.");
      }
      api.signedIn = true;
      return json(200, session);
    }
    if (path === "/auth/setup" && method === "GET") return json(200, { needed: api.setupNeeded });
    if (path === "/auth/setup" && method === "POST") {
      if (!api.setupNeeded) return problem(409, "setup_done", "An admin user already exists.");
      if (body.setup_token !== "local-test-token")
        return problem(403, "invalid_setup_token", "Invalid first-run setup token.");
      api.setupNeeded = false;
      api.signedIn = true;
      return json(200, session);
    }
    if (path === "/auth/logout" && method === "POST") {
      api.signedIn = false;
      return new Response(null, { status: 204 });
    }
    if (!api.signedIn) return problem(401, "not_authenticated", "Log in to use the admin.");
    if (path === "/auth/session") return json(200, session);
    if (path === "/schema") return json(200, schema);
    if (path === "/models/users/rows") return json(200, page(USERS, null, null));

    if (path === "/models/posts/rows" && method === "GET")
      return json(200, listPosts(posts, url.searchParams));
    if (path === "/models/posts/rows" && method === "POST") {
      if (api.failNextWith) return failValidation();
      const post: Post = {
        id: nextId++,
        title: String(body.title ?? ""),
        published: Boolean(body.published),
        author_id: (body.author_id as number | undefined) ?? null,
        version: 1,
      };
      posts.unshift(post);
      audit("create", { title: [null, post.title] });
      return json(201, toRow(post));
    }

    const action = /^\/models\/posts\/actions\/(\w+)$/.exec(path);
    if (action && method === "POST") {
      const selected = posts.filter((p) => (body.pks as string[]).includes(String(p.id)));
      if (action[1] === "publish") {
        for (const p of selected) Object.assign(p, { published: true, version: p.version + 1 });
        return json(200, { count: selected.length, message: `Published ${selected.length}.` });
      }
      for (const p of selected) posts.splice(posts.indexOf(p), 1);
      return json(200, { count: selected.length, message: null });
    }

    const history = /^\/models\/posts\/rows\/(\d+)\/history$/.exec(path);
    if (history) return json(200, { entries: api.history });

    const detail = /^\/models\/posts\/rows\/(.+)$/.exec(path);
    if (detail) {
      const post = posts.find((p) => String(p.id) === detail[1]);
      if (!post) return problem(404, "not_found", "Row not found.");
      if (method === "GET") return json(200, toRow(post));
      const ifMatch = headers["if-match"];
      if (!ifMatch) return problem(428, "precondition_required", "Send If-Match.");
      if (ifMatch !== `v${post.version}`) {
        return problem(409, "conflict", "This row was changed by someone else.", {
          current: toRow(post),
        });
      }
      if (method === "DELETE") {
        posts.splice(posts.indexOf(post), 1);
        return new Response(null, { status: 204 });
      }
      if (api.failNextWith) return failValidation();
      const before = { ...post };
      Object.assign(post, body, { version: post.version + 1 });
      audit("update", { title: [before.title, post.title] });
      return json(200, toRow(post));
    }
    return problem(404, "not_found", `fake API: no route ${method} ${path}`);
  });

  function failValidation() {
    const fields = api.failNextWith ?? {};
    api.failNextWith = null;
    return problem(400, "validation_failed", "invalid input", { fields });
  }

  globalThis.fetch = api.fetch as unknown as typeof fetch;
  return api;
}

function toRow(post: Post, detail = true): RowOut {
  const author = USERS.find((u) => u.values.id === post.author_id);
  return {
    pk: String(post.id),
    values: {
      id: post.id,
      title: post.title,
      published: post.published,
      author_id: post.author_id,
      author:
        post.author_id === null
          ? null
          : { pk: String(post.author_id), label: author ? String(author.values.email) : null },
    },
    version: detail ? `v${post.version}` : null,
  };
}

function page(rows: RowOut[], next: string | null, prev: string | null): ListOut {
  return { rows, next_cursor: next, prev_cursor: prev, pagination: "keyset", count: null };
}

/** Page size 2: page 1 = the first two posts with a next cursor, page 2 = the rest. */
function listPosts(posts: Post[], params: URLSearchParams): ListOut {
  const second = params.get("cursor") === "page-2";
  const rows = (second ? posts.slice(2) : posts.slice(0, 2)).map((p) => toRow(p, false));
  return {
    ...page(rows, second || posts.length <= 2 ? null : "page-2", second ? "page-1" : null),
    count:
      params.get("count") === "true"
        ? { value: posts.length, exact: true, method: "capped" }
        : null,
  };
}
