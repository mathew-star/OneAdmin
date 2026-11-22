import { useMutation } from "@tanstack/react-query";
import { useNavigate, useRouteContext } from "@tanstack/react-router";
import { LogOut } from "lucide-react";
import { isApiError } from "@/api/client";
import { useApp } from "@/lib/app";
import { Button } from "./ui";

/** Who is signed in, and sign-out (built-in authentication only). */
export function UserMenu() {
  const { config, client, queryClient } = useApp();
  const { session } = useRouteContext({ from: "/app" });
  const navigate = useNavigate();

  const logout = useMutation({
    mutationFn: () => client.post<void>("/auth/logout", {}),
    onError: (error) => {
      // An already-expired session is as good as signed out.
      if (isApiError(error, 401)) void finish();
    },
    onSuccess: () => finish(),
  });

  async function finish() {
    client.setCsrfToken(null);
    queryClient.clear();
    await navigate({ to: "/login" });
  }

  if (config.auth !== "builtin" || !session) return null;
  return (
    <div className="border-border border-t p-3">
      <p className="truncate px-2 pb-2 font-mono text-[11px] text-muted" title={session.user.email}>
        {session.user.email}
      </p>
      <Button
        variant="ghost"
        className="w-full justify-start text-xs"
        onClick={() => logout.mutate()}
        disabled={logout.isPending}
      >
        <LogOut className="size-4" aria-hidden="true" />
        {logout.isPending ? "Signing out…" : "Sign out"}
      </Button>
      {logout.isError && !isApiError(logout.error, 401) ? (
        <p role="alert" className="px-2.5 pt-1 text-danger text-xs">
          {logout.error.message}
        </p>
      ) : null}
    </div>
  );
}
