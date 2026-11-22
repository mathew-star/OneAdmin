import { useQuery } from "@tanstack/react-query";
import { historyQuery } from "@/api/queries";
import type { HistoryEntry, ModelSchema } from "@/api/types";
import { useApp } from "@/lib/app";
import { Notice, Spinner } from "./ui";

const ACTION_LABELS: Record<string, string> = {
  create: "Created",
  update: "Changed",
  delete: "Deleted",
};

/** The audit trail of one row (ADR-0018), newest first. Loaded when first shown. */
export function History({ model, pk }: { model: ModelSchema; pk: string }) {
  const { client } = useApp();
  const history = useQuery(historyQuery(client, model.slug, pk));
  if (history.isPending) return <Spinner label="Loading history" />;
  if (history.isError)
    return (
      <Notice tone="danger" title="History unavailable">
        {history.error.message}
      </Notice>
    );
  if (history.data.entries.length === 0) {
    return <p className="text-muted">No changes recorded through the admin yet.</p>;
  }
  const labelOf = (name: string) =>
    model.fields.find((f) => f.name === name)?.label ?? name.replace(/_/g, " ");

  return (
    <ol className="divide-y divide-border">
      {history.data.entries.map((entry) => (
        <li key={entry.id} className="py-4 first:pt-0 last:pb-0">
          <p className="text-xs">
            <span className="font-semibold text-fg">{actionLabel(entry)}</span>{" "}
            <span className="text-muted">
              by {entry.actor_email} · <time dateTime={entry.at}>{formatTime(entry.at)}</time>
            </span>
          </p>
          <table className="mt-2 w-full text-left text-xs">
            <caption className="sr-only">Changed fields</caption>
            <thead className="text-muted">
              <tr>
                <th scope="col" className="w-1/4 py-1 font-medium">
                  Field
                </th>
                <th scope="col" className="py-1 font-medium">
                  Before
                </th>
                <th scope="col" className="py-1 font-medium">
                  After
                </th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(entry.changes).map(([name, [before, after]]) => (
                <tr key={name} className="border-border border-t align-top">
                  <th scope="row" className="py-1 pr-2 font-normal text-muted">
                    {labelOf(name)}
                  </th>
                  <td className="break-all py-1 pr-2 font-mono">{show(before)}</td>
                  <td className="break-all py-1 font-mono">{show(after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </li>
      ))}
    </ol>
  );
}

function actionLabel(entry: HistoryEntry): string {
  if (entry.action.startsWith("action:"))
    return `Action "${entry.action.slice(7).replace(/_/g, " ")}"`;
  return ACTION_LABELS[entry.action] ?? entry.action;
}

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return typeof value === "string" ? value : JSON.stringify(value);
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}
