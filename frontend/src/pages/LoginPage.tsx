/**
 * Sign-in, and in development mode first-run setup: while no admin user exists, the server
 * reports `GET /auth/setup → {needed: true}` and this page offers to create the first
 * superuser instead (production uses `oneadmin createsuperuser`).
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter, useSearch } from "@tanstack/react-router";
import { Database } from "lucide-react";
import { type FormEvent, type ReactNode, useId, useState } from "react";
import { ApiError } from "@/api/client";
import { queryKeys } from "@/api/queries";
import type { SessionOut } from "@/api/types";
import { Button, Input, Spinner } from "@/components/ui";
import { useApp } from "@/lib/app";
import { safeNext } from "@/lib/safeNext";

export function LoginPage() {
  const { config, client } = useApp();
  const setup = useQuery({
    queryKey: ["setup"],
    queryFn: ({ signal }) => client.get<{ needed: boolean }>("/auth/setup", undefined, signal),
    enabled: config.dev,
    staleTime: Number.POSITIVE_INFINITY,
  });

  let body: ReactNode;
  if (config.dev && setup.isPending) body = <Spinner label="Checking setup" />;
  else if (config.dev && setup.data?.needed) body = <SetupForm />;
  else body = <SignInForm />;

  return (
    <main className="flex min-h-full items-center justify-center bg-bg p-4">
      <div className="w-full max-w-md">
        <div className="mb-8 flex items-center justify-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-xl bg-accent text-accent-fg">
            <Database className="size-5" aria-hidden="true" />
          </span>
          <span className="font-display font-semibold text-2xl">{config.title}</span>
          {config.dev ? <DevBadge /> : null}
        </div>
        {body}
      </div>
    </main>
  );
}

export function DevBadge() {
  return (
    <span
      title="Development mode"
      className="rounded-full bg-accent-soft px-2 py-0.5 font-medium text-accent text-xs"
    >
      Dev
    </span>
  );
}

/** After sign-in or setup: remember the session and go where the user was heading. */
function useEnterApp() {
  const { client, queryClient } = useApp();
  const { next } = useSearch({ from: "/login" });
  const router = useRouter();
  return async (session: SessionOut) => {
    client.setCsrfToken(session.csrf_token);
    queryClient.setQueryData(queryKeys.session, session);
    queryClient.setQueryData(["setup"], { needed: false });
    await router.navigate({ href: safeNext(next), replace: true });
  };
}

function SignInForm() {
  const { client } = useApp();
  const enter = useEnterApp();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const ids = { error: useId(), email: useId(), password: useId() };

  const login = useMutation({
    mutationFn: () =>
      client.post<SessionOut>("/auth/login", { email, password }, { withoutCsrf: true }),
    onSuccess: enter,
    onError: () => setPassword(""),
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!login.isPending) login.mutate();
  };
  const error = login.error ? loginErrorMessage(login.error) : null;

  return (
    <>
      <FormCard title="Sign in" error={error} errorId={ids.error} onSubmit={submit}>
        <Field id={ids.email} label="Email">
          <Input
            id={ids.email}
            type="email"
            name="email"
            autoComplete="username"
            required
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={error ? true : undefined}
          />
        </Field>
        <Field id={ids.password} label="Password">
          <Input
            id={ids.password}
            type="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={error ? true : undefined}
          />
        </Field>
        <Button
          type="submit"
          variant="primary"
          className="h-9 w-full"
          disabled={login.isPending || !email || !password}
        >
          {login.isPending ? "Signing in…" : "Sign in"}
        </Button>
      </FormCard>
      <p className="mt-4 text-center text-muted text-xs">
        No account? Ask an administrator to run{" "}
        <code className="font-mono">oneadmin createsuperuser</code>.
      </p>
    </>
  );
}

function SetupForm() {
  const { client } = useApp();
  const enter = useEnterApp();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [mismatch, setMismatch] = useState(false);
  const ids = {
    error: useId(),
    email: useId(),
    password: useId(),
    confirm: useId(),
    token: useId(),
  };

  const setup = useMutation({
    mutationFn: () =>
      client.post<SessionOut>(
        "/auth/setup",
        { email, password, setup_token: setupToken },
        { withoutCsrf: true },
      ),
    onSuccess: enter,
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const differs = password !== confirm;
    setMismatch(differs);
    if (!differs && !setup.isPending) setup.mutate();
  };
  const error = mismatch
    ? "The passwords don't match."
    : setup.error instanceof ApiError
      ? setup.error.message
      : setup.error
        ? "Setup failed. Try again."
        : null;

  return (
    <FormCard
      title="Create the first admin account"
      intro="No admin user exists yet. This account can do everything; create more later with the oneadmin CLI."
      error={error}
      errorId={ids.error}
      onSubmit={submit}
    >
      <Field id={ids.email} label="Email">
        <Input
          id={ids.email}
          type="email"
          autoComplete="username"
          required
          autoFocus
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </Field>
      <Field id={ids.password} label="Password" hint="At least 12 characters.">
        <Input
          id={ids.password}
          type="password"
          autoComplete="new-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </Field>
      <Field id={ids.confirm} label="Password (again)">
        <Input
          id={ids.confirm}
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          aria-invalid={mismatch ? true : undefined}
        />
      </Field>
      <Field id={ids.token} label="Setup token" hint="Copy this from the server terminal.">
        <Input
          id={ids.token}
          type="password"
          autoComplete="off"
          required
          value={setupToken}
          onChange={(e) => setSetupToken(e.target.value)}
        />
      </Field>
      <Button
        type="submit"
        variant="primary"
        className="h-9 w-full"
        disabled={setup.isPending || !email || !password || !confirm || !setupToken}
      >
        {setup.isPending ? "Creating…" : "Create account and sign in"}
      </Button>
    </FormCard>
  );
}

interface FormCardProps {
  title: string;
  intro?: string;
  error: string | null;
  errorId: string;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  children: ReactNode;
}

function FormCard({ title, intro, error, errorId, onSubmit, children }: FormCardProps) {
  return (
    <form
      onSubmit={onSubmit}
      noValidate
      aria-describedby={error ? errorId : undefined}
      className="space-y-5 rounded-xl border border-border bg-surface p-7 shadow-[0_12px_40px_-26px_var(--oa-shadow)]"
    >
      <h1 className="font-display font-semibold text-2xl">{title}</h1>
      {intro ? <p className="text-muted">{intro}</p> : null}
      {error ? (
        <p id={errorId} role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-danger">
          {error}
        </p>
      ) : null}
      {children}
    </form>
  );
}

function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block font-medium">
        {label}
      </label>
      {children}
      {hint ? <p className="text-muted text-xs">{hint}</p> : null}
    </div>
  );
}

function loginErrorMessage(error: Error): string {
  if (!(error instanceof ApiError)) return "Sign-in failed. Try again.";
  if (error.code === "rate_limited") {
    const minutes = error.retryAfter ? Math.max(1, Math.ceil(error.retryAfter / 60)) : null;
    return minutes
      ? `Too many failed attempts. Try again in ${minutes} minute${minutes === 1 ? "" : "s"}.`
      : "Too many failed attempts. Try again later.";
  }
  return error.message;
}
