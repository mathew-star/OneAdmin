import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { Pencil, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { ApiError, isApiError } from "@/api/client";
import { deleteRow } from "@/api/mutations";
import { rowQuery } from "@/api/queries";
import type { ModelSchema, RowOut } from "@/api/types";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { History } from "@/components/History";
import { Cell } from "@/components/list/DataTable";
import { RecordPageHeader } from "@/components/RecordPageHeader";
import { useToast } from "@/components/Toaster";
import { Button, buttonClass, Notice, Spinner } from "@/components/ui";
import { useApp, useModel } from "@/lib/app";
import { detailColumns } from "@/lib/columns";
import { isRelationValue } from "@/lib/format";

/** A row's display title: its label field, else "<Model> <pk>". */
export function rowTitle(model: ModelSchema, row: RowOut): string {
  const label = row.values[model.label_field];
  return label === null || label === undefined || isRelationValue(label)
    ? `${model.name} ${row.pk}`
    : String(label);
}

export function DetailPage() {
  const { slug, pk } = useParams({ from: "/app/m/$slug/r/$pk" });
  const model = useModel(slug);
  const { client, queryClient, listMemory } = useApp();
  const navigate = useNavigate();
  const toast = useToast();
  const columns = useMemo(() => detailColumns(model), [model]);
  const row = useQuery(rowQuery(client, slug, pk));
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  // 404 is expected (deleted, or outside the viewer's scope); anything else is the
  // route error boundary's job.
  if (row.isError && !isApiError(row.error, 404)) throw row.error;

  const remove = async (current: RowOut) => {
    setDeleting(true);
    try {
      await deleteRow(client, queryClient, slug, current.pk, current.version ?? "");
      toast.show(`${model.name} deleted.`);
      await navigate({ to: "/m/$slug", params: { slug }, search: listMemory.recall(slug) });
    } catch (error) {
      setConfirming(false);
      if (error instanceof ApiError && error.code === "conflict") {
        await row.refetch();
        toast.show(
          "Someone changed this row in the meantime. Review it and delete again.",
          "error",
        );
      } else {
        toast.show(error instanceof Error ? error.message : "Delete failed.", "error");
      }
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="min-h-full bg-bg">
      <RecordPageHeader
        model={model}
        title={row.data ? rowTitle(model, row.data) : pk}
        breadcrumb={row.data ? rowTitle(model, row.data) : pk}
        context="Record"
        actions={
          row.data ? (
            <>
              {model.permissions.change ? (
                <Link
                  to="/m/$slug/r/$pk/edit"
                  params={{ slug, pk }}
                  className={buttonClass("primary")}
                >
                  <Pencil className="size-3.5" aria-hidden="true" />
                  Edit
                </Link>
              ) : null}
              {model.permissions.delete ? (
                <Button variant="secondary" onClick={() => setConfirming(true)}>
                  <Trash2 className="size-3.5 text-danger" aria-hidden="true" />
                  Delete
                </Button>
              ) : null}
            </>
          ) : null
        }
      />

      <div className="mx-auto max-w-6xl space-y-5 p-4 md:p-6">
        {row.isError ? (
          <Notice title={`${model.name} not found`}>
            It may have been deleted, or it's outside what you can see.
          </Notice>
        ) : row.data === undefined ? (
          <div className="py-12 text-center">
            <Spinner label={`Loading ${model.name}`} />
          </div>
        ) : (
          <>
            <section aria-labelledby="fields-heading" className="border border-border bg-surface">
              <div className="flex items-center justify-between gap-3 border-border border-b px-4 py-3">
                <h2 id="fields-heading" className="font-semibold text-sm">
                  Record fields
                </h2>
                <span className="font-mono text-[11px] text-muted tabular">
                  {String(columns.length).padStart(2, "0")} fields
                </span>
              </div>
              <dl className="divide-y divide-border">
                {columns.map((column) => (
                  <div
                    key={column.name}
                    className="grid sm:grid-cols-[minmax(12rem,14rem)_minmax(0,1fr)]"
                  >
                    <dt className="border-border bg-surface-muted px-4 py-3 text-muted text-xs font-medium sm:border-r">
                      <span className="block text-fg">{column.label}</span>
                      <span
                        className="mt-0.5 block font-mono text-[10px] text-muted"
                        aria-hidden="true"
                      >
                        {column.name} ·{" "}
                        {column.type === "relation" ? "relation" : column.field.kind}
                      </span>
                    </dt>
                    <dd className="min-w-0 break-words px-4 py-3">
                      <Cell column={column} value={row.data.values[column.name]} full />
                    </dd>
                  </div>
                ))}
              </dl>
            </section>

            <section aria-labelledby="history-heading" className="border border-border bg-surface">
              <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div>
                  <h2 id="history-heading" className="font-semibold text-sm">
                    Activity
                  </h2>
                  <p className="mt-0.5 text-muted text-xs">Changes made through this admin.</p>
                </div>
                {!showHistory ? (
                  <Button onClick={() => setShowHistory(true)}>Show changes</Button>
                ) : null}
              </div>
              {showHistory ? (
                <div className="border-border border-t p-4">
                  <History model={model} pk={pk} />
                </div>
              ) : null}
            </section>

            <ConfirmDialog
              open={confirming}
              onOpenChange={setConfirming}
              title={`Delete ${rowTitle(model, row.data)}?`}
              description="This can't be undone. The deletion is recorded in the audit log."
              confirmLabel="Delete"
              destructive
              busy={deleting}
              onConfirm={() => void remove(row.data)}
            />
          </>
        )}
      </div>
    </div>
  );
}
