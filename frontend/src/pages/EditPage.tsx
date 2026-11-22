import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { isApiError } from "@/api/client";
import { rowQuery } from "@/api/queries";
import type { RowOut } from "@/api/types";
import { RecordForm } from "@/components/form/RecordForm";
import { RecordPageHeader } from "@/components/RecordPageHeader";
import { useToast } from "@/components/Toaster";
import { Notice, Spinner } from "@/components/ui";
import { useApp, useModel } from "@/lib/app";
import { rowTitle } from "./DetailPage";

export function EditPage() {
  const { slug, pk } = useParams({ from: "/app/m/$slug/r/$pk/edit" });
  const model = useModel(slug);
  const { client } = useApp();
  const navigate = useNavigate();
  const toast = useToast();
  // Always start from the server's current version, never a cached one.
  const row = useQuery({ ...rowQuery(client, slug, pk), staleTime: 0, refetchOnMount: "always" });
  const recordKey = `${slug}\u0000${pk}`;
  const [seed, setSeed] = useState<{ key: string; row: RowOut } | null>(null);
  useEffect(() => {
    // Capture the first fresh row. Later refetches must not replace a user's draft;
    // If-Match and the conflict flow handle changes made by another editor.
    if (!row.data || row.isFetching) return;
    setSeed((current) =>
      current?.key === recordKey ? current : { key: recordKey, row: row.data },
    );
  }, [recordKey, row.data, row.isFetching]);
  const editingRow = seed?.key === recordKey ? seed.row : undefined;
  if (row.isError && !isApiError(row.error, 404)) throw row.error;
  const back = () => void navigate({ to: "/m/$slug/r/$pk", params: { slug, pk } });

  return (
    <div className="min-h-full bg-bg">
      <RecordPageHeader
        model={model}
        title={
          editingRow ? `Edit ${rowTitle(model, editingRow)}` : `Edit ${model.name.toLowerCase()}`
        }
        breadcrumb="Edit"
        parentRecord={editingRow ? { pk, label: rowTitle(model, editingRow) } : undefined}
        context="Editing record"
      />
      <div className="mx-auto max-w-6xl p-4 md:p-6">
        {row.isError ? (
          <Notice title={`${model.name} not found`}>
            It may have been deleted, or it's outside what you can see.
          </Notice>
        ) : !editingRow ? (
          <div className="py-12 text-center">
            <Spinner label={`Loading ${model.name}`} />
          </div>
        ) : !model.permissions.change ? (
          <Notice title="You can't edit this row">
            Ask an administrator for the "{slug}.change" permission.
          </Notice>
        ) : (
          <RecordForm
            key={recordKey}
            model={model}
            row={editingRow}
            onSaved={() => {
              toast.show("Changes saved.");
              back();
            }}
            onCancel={back}
          />
        )}
      </div>
    </div>
  );
}
