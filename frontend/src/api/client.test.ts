import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError } from "./client";

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  return vi.fn(async () =>
    status === 204
      ? new Response(null, { status })
      : new Response(JSON.stringify(body), {
          status,
          headers: { "content-type": "application/json", ...headers },
        }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("ApiClient", () => {
  it("builds URLs under the API base, dropping undefined params", () => {
    const client = new ApiClient("/admin/api/v1/");
    expect(client.url("/models/x/rows", { sort: "-id", q: undefined, "f.a__eq": "b c" })).toBe(
      "/admin/api/v1/models/x/rows?sort=-id&f.a__eq=b+c",
    );
  });

  it("sends the CSRF token on unsafe requests", async () => {
    const fetch = respond(204, null);
    vi.stubGlobal("fetch", fetch);
    const client = new ApiClient("/api");
    client.setCsrfToken("t0ken");
    await client.post("/auth/logout", {});
    const [, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.headers).toMatchObject({
      "x-csrf-token": "t0ken",
      "content-type": "application/json",
    });
    expect(init.credentials).toBe("same-origin");
  });

  it("refuses an unsafe request without a token instead of sending it", async () => {
    const fetch = respond(204, null);
    vi.stubGlobal("fetch", fetch);
    await expect(new ApiClient("/api").post("/auth/logout", {})).rejects.toMatchObject({
      code: "csrf_failed",
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("allows the login request without a token", async () => {
    vi.stubGlobal("fetch", respond(200, { ok: true }));
    await expect(
      new ApiClient("/api").post("/auth/login", {}, { withoutCsrf: true }),
    ).resolves.toEqual({ ok: true });
  });

  it("turns error bodies into ApiError with code, param and Retry-After", async () => {
    vi.stubGlobal(
      "fetch",
      respond(
        429,
        { error: { code: "rate_limited", message: "Slow down", param: null } },
        { "retry-after": "120" },
      ),
    );
    const error = await new ApiClient("/api").get("/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 429,
      code: "rate_limited",
      message: "Slow down",
      retryAfter: 120,
    });
  });

  it("copes with non-JSON error pages (e.g. a proxy's 502)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html>Bad gateway</html>", { status: 502 })),
    );
    await expect(new ApiClient("/api").get("/x")).rejects.toMatchObject({
      status: 502,
      code: "http_error",
    });
  });

  it("reports network failures as status 0", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))),
    );
    await expect(new ApiClient("/api").get("/x")).rejects.toMatchObject({
      status: 0,
      code: "network_error",
    });
  });
});
