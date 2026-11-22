/**
 * Create and edit form, generated from the model schema (M6).
 *
 * - Writable fields become inputs; on edit, the rest is shown read-only.
 * - Edits send only changed fields, with the row's version (`If-Match`).
 * - `400 validation_failed` puts each message under its field and focuses a summary.
 * - `409 conflict` shows what someone else changed and offers to rebase: the latest row
 *   becomes the base, the user's own edits are kept on top, and they save again.
 */
import { type FormEvent, useId, useMemo, useRef, useState } from "react";
import { ApiError } from "@/api/client";
import { createRow, updateRow } from "@/api/mutations";
import type { FieldSchema, ModelSchema, RowOut } from "@/api/types";
import { useApp, useSchema } from "@/lib/app";
import { isRelationValue } from "@/lib/format";
import {
  blankDrafts,
  buildPayload,
  changedFields,
  type Drafts,
  initialDrafts,
} from "@/lib/formValues";
import { Cell } from "../list/DataTable";
import { Button, Notice } from "../ui";
import { FieldInput } from "./FieldInput";
import { RelationPicker } from "./RelationPicker";

interface RecordFormProps {
  model: ModelSchema;
  /** The row being edited; omit to create. */
  row?: RowOut;
  onSaved: (row: RowOut) => void;
  onCancel: () => void;
}

interface Base {
  drafts: Drafts;
  version: string | null;
  values: Record<string, unknown>;
}

export function RecordForm({ model, row, onSaved, onCancel }: RecordFormProps) {
  const { client, queryClient } = useApp();
  const schema = useSchema();
  const formId = useId();
  const summaryRef = useRef<HTMLDivElement>(null);
  const mode = row ? "update" : "create";

  const editable = useMemo(
    () => model.fields.filter((f) => f.writable && !(mode === "update" && f.primary_key)),
    [model, mode],
  );
  const [base, setBase] = useState<Base>(() => ({
    drafts: row ? initialDrafts(editable, row.values) : blankDrafts(editable),
    version: row?.version ?? null,
    values: row?.values ?? {},
  }));
  const [drafts, setDrafts] = useState<Drafts>(base.drafts);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<RowOut | null>(null);
  const [saving, setSaving] = useState(false);

  const relations = useMemo(() => new Map(model.relations.map((r) => [r.local_field, r])), [model]);
  const fieldId = (name: string) => `${formId}-${name}`;
  const errorId = (name: string) => (errors[name] ? `${fieldId(name)}-error` : undefined);
  const changed = changedFields(base.drafts, drafts);

  const focusSummary = () => requestAnimationFrame(() => summaryRef.current?.focus());

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving) return;
    if (mode === "update" && changed.length === 0 && row) {
      onSaved(row);
      return;
    }
    setSaving(true);
    setErrors({});
    setFormError(null);
    try {
      const body = buildPayload(mode, editable, base.drafts, drafts);
      const saved =
        mode === "create"
          ? await createRow(client, queryClient, model.slug, body)
          : await updateRow(
              client,
              queryClient,
              model.slug,
              row?.pk ?? "",
              base.version ?? "",
              body,
            );
      onSaved(saved);
    } catch (error) {
      showError(error);
    } finally {
      setSaving(false);
    }
  };

  function showError(error: unknown) {
    if (!(error instanceof ApiError)) {
      setFormError("Saving failed unexpectedly. Try again.");
    } else if (error.code === "conflict" && error.current) {
      setConflict(error.current);
    } else if (error.code === "validation_failed") {
      const { "": general, ...byField } = error.fields;
      setErrors(byField);
      setFormError(general ?? null);
    } else if (error.code === "integrity_error" && error.param) {
      setErrors({ [error.param]: "This value conflicts with another row (it must be unique)." });
      setFormError(error.message);
    } else {
      setFormError(error.message);
    }
    focusSummary();
  }

  /** Make the latest row the base, keeping the user's own edits on top. */
  function rebase(current: RowOut) {
    const theirs = initialDrafts(editable, current.values);
    const mine = Object.fromEntries(changed.map((name) => [name, drafts[name] as Drafts[string]]));
    setBase({ drafts: theirs, version: current.version ?? null, values: current.values });
    setDrafts({ ...theirs, ...mine });
    setConflict(null);
    setFormError(null);
  }

  const errorCount = Object.keys(errors).length;
  const othersChanged = conflict
    ? changedFields(base.drafts, initialDrafts(editable, conflict.values)).map(
        (name) => editable.find((f) => f.name === name)?.label ?? name,
      )
    : [];

  return (
    <form id={formId} onSubmit={submit} noValidate className="space-y-5">
      <div ref={summaryRef} tabIndex={-1} className="focus:outline-none">
        {conflict ? (
          <Notice
            tone="danger"
            title="Someone else changed this row while you were editing"
            action={
              <Button variant="primary" onClick={() => rebase(conflict)}>
                Use the latest version, keep my changes
              </Button>
            }
          >
            {othersChanged.length
              ? `They changed: ${othersChanged.join(", ")}. `
              : "Their changes are in fields you can't edit here. "}
            Your edits ({changed.length}) are kept; review the result and save again.
          </Notice>
        ) : errorCount || formError ? (
          <Notice
            tone="danger"
            title={
              errorCount
                ? `Please fix ${errorCount} field${errorCount > 1 ? "s" : ""}`
                : "Not saved"
            }
          >
            {formError ? <p>{formError}</p> : null}
            {errorCount ? (
              <ul className="mt-1 list-disc pl-5">
                {Object.entries(errors).map(([name, message]) => (
                  <li key={name}>
                    <a
                      href={`#${fieldId(name)}`}
                      onClick={(e) => {
                        e.preventDefault(); // <base href> would turn the fragment into a navigation
                        document.getElementById(fieldId(name))?.focus();
                      }}
                      className="underline"
                    >
                      {labelOf(model.fields, name)}
                    </a>
                    : {message}
                  </li>
                ))}
              </ul>
            ) : null}
          </Notice>
        ) : null}
      </div>

      <section aria-labelledby={`${formId}-fields`} className="border border-border bg-surface">
        <div className="flex flex-wrap items-center justify-between gap-2 border-border border-b px-4 py-3">
          <h2 id={`${formId}-fields`} className="font-semibold text-sm">
            Record fields
          </h2>
          <span className="font-mono text-[11px] text-muted tabular">
            {String(editable.length).padStart(2, "0")} editable
          </span>
        </div>
        <div className="divide-y divide-border">
          {model.fields.map((field) => {
            const isEditable = editable.includes(field);
            if (!isEditable && mode === "create") return null;
            const relation = relations.get(field.name);
            const target = relation?.target
              ? schema.models.find((m) => m.slug === relation.target)
              : undefined;
            const message = errors[field.name];
            return (
              <div
                key={field.name}
                className="grid sm:grid-cols-[minmax(12rem,14rem)_minmax(0,1fr)]"
              >
                <div className="border-border bg-surface-muted px-4 py-3 text-xs sm:border-r">
                  <label
                    htmlFor={isEditable ? fieldId(field.name) : undefined}
                    className="block font-medium text-fg"
                  >
                    {relation?.label ?? field.label}
                    {isEditable && field.required ? (
                      <span aria-hidden="true" className="text-danger">
                        {" "}
                        *
                      </span>
                    ) : null}
                    {isEditable && field.required ? (
                      <span className="sr-only"> (required)</span>
                    ) : null}
                  </label>
                  <span
                    className="mt-0.5 block font-mono text-[10px] text-muted"
                    aria-hidden="true"
                  >
                    {field.name} · {field.kind}
                    {!isEditable ? " · read only" : ""}
                  </span>
                </div>
                <div className="min-w-0 space-y-1 px-4 py-3">
                  {!isEditable ? (
                    <div className="py-1.5">
                      <Cell
                        column={{ type: "field", name: field.name, label: field.label, field }}
                        value={base.values[field.name]}
                        full
                      />
                    </div>
                  ) : target && relation ? (
                    <RelationPicker
                      id={fieldId(field.name)}
                      target={target}
                      value={String(drafts[field.name] ?? "")}
                      initialLabel={relationLabel(base.values[relation.name])}
                      nullable={field.nullable}
                      onChange={(pk) => setDrafts((d) => ({ ...d, [field.name]: pk }))}
                      errorId={errorId(field.name)}
                    />
                  ) : (
                    <FieldInput
                      id={fieldId(field.name)}
                      field={field}
                      value={drafts[field.name] ?? ""}
                      onChange={(value) => setDrafts((d) => ({ ...d, [field.name]: value }))}
                      errorId={errorId(field.name)}
                      allowBlank={field.nullable || mode === "create"}
                    />
                  )}
                  {message ? (
                    <p id={errorId(field.name)} className="text-danger text-xs">
                      {message}
                    </p>
                  ) : null}
                  {isEditable && field.kind === "datetime" && field.tz_aware ? (
                    <p className="text-muted text-xs">In your local time zone.</p>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <div className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-3 border border-border bg-surface px-4 py-3 shadow-[0_-8px_24px_-18px_var(--oa-shadow)]">
        <span className="font-mono text-[11px] text-muted" aria-live="polite">
          {mode === "update"
            ? changed.length
              ? `${changed.length} unsaved change${changed.length > 1 ? "s" : ""}`
              : "No changes"
            : "* Required fields"}
        </span>
        <div className="flex items-center gap-2">
          <Button onClick={onCancel}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={saving || conflict !== null}>
            {saving
              ? "Saving…"
              : mode === "create"
                ? `Create ${model.name.toLowerCase()}`
                : "Save changes"}
          </Button>
        </div>
      </div>
    </form>
  );
}

function labelOf(fields: readonly FieldSchema[], name: string): string {
  return fields.find((f) => f.name === name)?.label ?? (name || "Form");
}

function relationLabel(value: unknown): string | null {
  return isRelationValue(value) ? value.label : null;
}
