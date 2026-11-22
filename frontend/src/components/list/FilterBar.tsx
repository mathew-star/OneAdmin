import { Link } from "@tanstack/react-router";
import { ListFilter, X } from "lucide-react";
import { Popover } from "radix-ui";
import { type FormEvent, useId, useMemo, useState } from "react";
import type { FieldSchema, ModelSchema } from "@/api/types";
import { describeFilter, opLabel, toWireValue } from "@/lib/filterText";
import { activeFilters, type ListSearch, withFilter, withoutFilter } from "@/lib/listSearch";
import { Button, Input, Select } from "../ui";

interface FilterBarProps {
  model: ModelSchema;
  search: ListSearch;
  onApply: (search: ListSearch) => void;
}

/** Active filters as removable chips, plus an "Add filter" form for the allowed fields. */
export function FilterBar({ model, search, onApply }: FilterBarProps) {
  const filterable = useMemo(() => filterableFields(model), [model]);
  const filters = activeFilters(search);
  const fieldOf = (name: string) => model.fields.find((f) => f.name === name);

  if (filterable.length === 0 && filters.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {filterable.length > 0 ? (
        <AddFilter
          fields={filterable}
          onAdd={(field, op, value) => onApply(withFilter(search, field, op, value))}
        />
      ) : null}
      {filters.map((filter) => (
        <span
          key={filter.key}
          className="inline-flex h-7 items-center gap-1 rounded-[4px] border border-border bg-surface-muted pr-1 pl-2.5 font-mono text-[11px]"
        >
          {describeFilter(filter, fieldOf(filter.field))}
          <Link
            to="/m/$slug"
            params={{ slug: model.slug }}
            search={withoutFilter(search, filter.key)}
            className="rounded-sm p-0.5 text-muted hover:bg-surface hover:text-fg"
            aria-label={`Remove filter: ${describeFilter(filter, fieldOf(filter.field))}`}
          >
            <X className="size-3.5" aria-hidden="true" />
          </Link>
        </span>
      ))}
    </div>
  );
}

/** Fields in `list_filter` order first, then any other field the server allows filtering. */
function filterableFields(model: ModelSchema): FieldSchema[] {
  const allowed = model.fields.filter((f) => f.filter_ops.length > 0);
  const rank = (f: FieldSchema) => {
    const i = model.list_filter.indexOf(f.name);
    return i < 0 ? Number.MAX_SAFE_INTEGER : i;
  };
  return [...allowed].sort((a, b) => rank(a) - rank(b));
}

interface AddFilterProps {
  fields: FieldSchema[];
  onAdd: (field: string, op: string, value: string) => void;
}

function AddFilter({ fields, onAdd }: AddFilterProps) {
  const [open, setOpen] = useState(false);
  const [fieldName, setFieldName] = useState(fields[0]?.name ?? "");
  const field = fields.find((f) => f.name === fieldName) ?? fields[0];
  const [op, setOp] = useState(field?.filter_ops[0] ?? "eq");
  const [value, setValue] = useState("");
  const ids = { field: useId(), op: useId(), value: useId() };

  if (!field) return null;
  const effectiveOp = field.filter_ops.includes(op) ? op : (field.filter_ops[0] ?? "eq");

  const chooseField = (name: string) => {
    const next = fields.find((f) => f.name === name);
    setFieldName(name);
    setOp(next?.filter_ops[0] ?? "eq");
    setValue(defaultValue(next, next?.filter_ops[0]));
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const raw = value || defaultValue(field, effectiveOp);
    if (!raw.trim()) return;
    onAdd(field.name, effectiveOp, toWireValue(field, effectiveOp, raw));
    setOpen(false);
    setValue("");
  };

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <Button className="h-8 text-xs">
          <ListFilter className="size-3.5" aria-hidden="true" />
          Add filter
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={6}
          className="z-50 w-72 rounded-lg border border-border bg-surface p-3 shadow-lg"
        >
          <form onSubmit={submit} className="space-y-3">
            <div className="space-y-1">
              <label htmlFor={ids.field} className="font-medium text-xs">
                Field
              </label>
              <Select
                id={ids.field}
                value={field.name}
                onChange={(e) => chooseField(e.target.value)}
              >
                {fields.map((f) => (
                  <option key={f.name} value={f.name}>
                    {f.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1">
              <label htmlFor={ids.op} className="font-medium text-xs">
                Condition
              </label>
              <Select
                id={ids.op}
                value={effectiveOp}
                onChange={(e) => {
                  setOp(e.target.value);
                  setValue(defaultValue(field, e.target.value));
                }}
              >
                {field.filter_ops.map((o) => (
                  <option key={o} value={o}>
                    {opLabel(o, field)}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1">
              <label htmlFor={ids.value} className="font-medium text-xs">
                Value
              </label>
              <ValueInput
                id={ids.value}
                field={field}
                op={effectiveOp}
                value={value}
                onChange={setValue}
              />
            </div>
            <div className="flex justify-end gap-2">
              <Popover.Close asChild>
                <Button variant="ghost">Cancel</Button>
              </Popover.Close>
              <Button type="submit" variant="primary">
                Apply
              </Button>
            </div>
          </form>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

/** Choice-like inputs have a sensible first value; free-text ones start empty. */
function defaultValue(field: FieldSchema | undefined, op: string | undefined): string {
  if (!field) return "";
  if (op === "isnull" || field.kind === "boolean") return "true";
  if (field.kind === "enum" && op !== "in") return field.enum_values?.[0] ?? "";
  return "";
}

interface ValueInputProps {
  id: string;
  field: FieldSchema;
  op: string;
  value: string;
  onChange: (value: string) => void;
}

/** The value control for a field's kind and operator. */
function ValueInput({ id, field, op, value, onChange }: ValueInputProps) {
  const current = value || defaultValue(field, op);
  if (op === "isnull") {
    return (
      <Select id={id} value={current} onChange={(e) => onChange(e.target.value)}>
        <option value="true">is empty</option>
        <option value="false">is not empty</option>
      </Select>
    );
  }
  if (field.kind === "boolean") {
    return (
      <Select id={id} value={current} onChange={(e) => onChange(e.target.value)}>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </Select>
    );
  }
  if (field.kind === "enum" && field.enum_values && op !== "in") {
    return (
      <Select id={id} value={current} onChange={(e) => onChange(e.target.value)}>
        {field.enum_values.map((v) => (
          <option key={v} value={v}>
            {v}
          </option>
        ))}
      </Select>
    );
  }
  const common = {
    id,
    value,
    onChange: (e: { target: { value: string } }) => onChange(e.target.value),
    required: true,
  };
  if (op === "in") {
    const hint = field.enum_values ? field.enum_values.slice(0, 3).join(", ") : "a, b, c";
    return <Input {...common} placeholder={hint} />;
  }
  switch (field.kind) {
    case "date":
      return <Input {...common} type="date" />;
    case "datetime":
      return <Input {...common} type="datetime-local" step={1} />;
    case "time":
      return <Input {...common} type="time" step={1} />;
    case "integer":
      return <Input {...common} inputMode="numeric" />;
    case "decimal":
    case "float":
      return <Input {...common} inputMode="decimal" />;
    default:
      return <Input {...common} maxLength={field.max_length ?? 500} />;
  }
}
