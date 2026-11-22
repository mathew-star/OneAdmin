import { type ErrorComponentProps, Link, useRouter } from "@tanstack/react-router";
import { isApiError } from "@/api/client";
import { Button, Notice } from "./ui";

/**
 * Errors that escape a page. API errors are explained in the admin's terms; anything else
 * is a bug, so it is logged and shown with a retry.
 */
export function RouteError({ error, reset }: ErrorComponentProps) {
  const router = useRouter();
  const retry = () => {
    reset();
    void router.invalidate();
  };

  let title = "Something went wrong";
  let body: React.ReactNode = error instanceof Error ? error.message : String(error);

  if (isApiError(error)) {
    switch (error.code) {
      case "admin_not_migrated":
        title = "The admin isn't set up yet";
        body = (
          <>
            OneAdmin's tables don't exist in this database. Run{" "}
            <code className="font-mono">oneadmin migrate</code>, then{" "}
            <code className="font-mono">oneadmin createsuperuser</code>.
          </>
        );
        break;
      case "forbidden":
        title = "You don't have access";
        break;
      case "unknown_model":
      case "not_found":
        title = "Not found";
        break;
      case "network_error":
        title = "Can't reach the server";
        break;
      default:
        break;
    }
  } else {
    console.error(error);
  }

  return (
    <div className="p-6">
      <Notice
        tone="danger"
        title={title}
        action={
          <div className="flex gap-2">
            <Button onClick={retry}>Try again</Button>
            <Link to="/" className="inline-flex h-8 items-center px-2 text-accent hover:underline">
              Go to the start page
            </Link>
          </div>
        }
      >
        {body}
      </Notice>
    </div>
  );
}
