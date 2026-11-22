import { useMutation } from "@tanstack/react-query";
import { useId, useState } from "react";
import { runAction } from "@/api/mutations";
import type { ActionSchema, ModelSchema } from "@/api/types";
import { useApp } from "@/lib/app";
import { ConfirmDialog } from "../ConfirmDialog";
import { useToast } from "../Toaster";
import { Button, Select } from "../ui";

interface ActionBarProps {
  model: ModelSchema;
  selected: string[];
  onDone: () => void;
}

/**
 * Run a bulk action on the selected rows. Actions that declare `confirm`, or are
 * destructive, ask first. The server re-checks permission and scope for every row and
 * applies the action to all of them or none.
 */
export function ActionBar({ model, selected, onDone }: ActionBarProps) {
  const { client, queryClient } = useApp();
  const toast = useToast();
  const selectId = useId();
  const [name, setName] = useState(model.actions[0]?.name ?? "");
  const [confirming, setConfirming] = useState<ActionSchema | null>(null);
  const action = model.actions.find((a) => a.name === name);

  const run = useMutation({
    mutationFn: (target: ActionSchema) =>
      runAction(client, queryClient, model.slug, target.name, selected),
    onSuccess: (result, target) => {
      setConfirming(null);
      toast.show(
        result.message ?? `${target.label}: done for ${result.count} ${noun(model, result.count)}.`,
      );
      onDone();
    },
    onError: (error) => {
      setConfirming(null);
      toast.show(error.message, "error");
    },
  });

  const start = () => {
    if (!action) return;
    if (action.confirm || action.destructive) setConfirming(action);
    else run.mutate(action);
  };

  const count = selected.length;
  return (
    <section
      aria-label="Bulk actions"
      className="flex flex-wrap items-center gap-2 rounded-lg border border-accent/30 bg-accent-soft px-3 py-2"
    >
      <span className="font-medium">
        {count} {noun(model, count)} selected
      </span>
      <label htmlFor={selectId} className="sr-only">
        Action
      </label>
      {/* A fixed-width wrapper: the shared input styles are full-width. */}
      <div className="w-56">
        <Select
          id={selectId}
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="h-7 text-xs"
        >
          {model.actions.map((a) => (
            <option key={a.name} value={a.name}>
              {a.label}
            </option>
          ))}
        </Select>
      </div>
      <Button
        variant={action?.destructive ? "danger" : "primary"}
        className="h-7 text-xs"
        onClick={start}
        disabled={!action || run.isPending}
      >
        {run.isPending ? "Running…" : "Run"}
      </Button>
      <Button variant="ghost" className="h-7 text-xs" onClick={onDone}>
        Clear selection
      </Button>
      {confirming ? (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && setConfirming(null)}
          title={`${confirming.label}: ${count} ${noun(model, count)}?`}
          description={confirming.confirm ?? "This can't be undone."}
          confirmLabel={confirming.label}
          destructive={confirming.destructive}
          busy={run.isPending}
          onConfirm={() => run.mutate(confirming)}
        />
      ) : null}
    </section>
  );
}

function noun(model: ModelSchema, n: number): string {
  return (n === 1 ? model.name : model.name_plural).toLowerCase();
}
