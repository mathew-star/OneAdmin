import { useNavigate, useParams } from "@tanstack/react-router";
import { RecordForm } from "@/components/form/RecordForm";
import { RecordPageHeader } from "@/components/RecordPageHeader";
import { useToast } from "@/components/Toaster";
import { Notice } from "@/components/ui";
import { useModel } from "@/lib/app";

export function CreatePage() {
  const { slug } = useParams({ from: "/app/m/$slug/new" });
  const model = useModel(slug);
  const navigate = useNavigate();
  const toast = useToast();
  const title = `New ${model.name.toLowerCase()}`;

  return (
    <div className="min-h-full bg-bg">
      <RecordPageHeader model={model} title={title} breadcrumb={title} context="Creating record" />
      <div className="mx-auto max-w-6xl p-4 md:p-6">
        {model.permissions.add ? (
          <RecordForm
            model={model}
            onSaved={(row) => {
              toast.show(`${model.name} created.`);
              void navigate({ to: "/m/$slug/r/$pk", params: { slug, pk: row.pk } });
            }}
            onCancel={() => void navigate({ to: "/m/$slug", params: { slug } })}
          />
        ) : (
          <Notice title="You can't add rows here">
            Ask an administrator for the "{slug}.add" permission.
          </Notice>
        )}
      </div>
    </div>
  );
}
