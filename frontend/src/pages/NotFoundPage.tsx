import { Link } from "@tanstack/react-router";
import { Notice } from "@/components/ui";

export function NotFoundPage() {
  return (
    <div className="p-6">
      <Notice
        title="Page not found"
        action={
          <Link to="/" className="text-accent hover:underline">
            Go to the start page
          </Link>
        }
      >
        This address doesn't match any admin page or registered model.
      </Notice>
    </div>
  );
}
