import type { FieldSchema } from "@/api/types";
import { cx, useApp } from "@/lib/app";
import type { Draft } from "@/lib/formValues";
import { Input, inputClass, Select } from "../ui";

export interface FieldInputProps {
  id: string;
  field: FieldSchema;
  value: Draft;
  onChange: (value: Draft) => void;
  /** `id` of the element describing the current error, if any. */
  errorId?: string | undefined;
  /** Offer an empty choice in selects (nullable columns, or blank on create). */
  allowBlank: boolean;
}

/** The input for one writable field: its widget's input if registered, else by kind. */
export function FieldInput(props: FieldInputProps) {
  const { widgets } = useApp();
  const Custom = typeof props.value === "boolean" ? null : widgets.input(props.field);
  return Custom ? <Custom {...props} /> : <KindInput {...props} />;
}

function KindInput({ id, field, value, onChange, errorId, allowBlank }: FieldInputProps) {
  const a11y = {
    id,
    "aria-invalid": errorId ? true : undefined,
    "aria-describedby": errorId,
    "aria-required": field.required || undefined,
  };

  if (typeof value === "boolean") {
    return (
      <input
        {...a11y}
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
        className="size-4 accent-[var(--oa-accent)]"
      />
    );
  }

  const text = (e: { target: { value: string } }) => onChange(e.target.value);

  if (field.kind === "boolean") {
    return (
      <Select {...a11y} value={value} onChange={text} className="max-w-48">
        <option value="">—</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </Select>
    );
  }
  if (field.kind === "enum" && field.enum_values) {
    return (
      <Select {...a11y} value={value} onChange={text} className="max-w-sm">
        {allowBlank || value === "" ? <option value="">—</option> : null}
        {field.enum_values.map((choice) => (
          <option key={choice} value={choice}>
            {choice}
          </option>
        ))}
      </Select>
    );
  }
  if (field.kind === "text") {
    return (
      <textarea
        {...a11y}
        value={value}
        onChange={text}
        rows={5}
        className={cx(inputClass, "h-auto py-1.5")}
      />
    );
  }

  const common = { ...a11y, value, onChange: text };
  switch (field.kind) {
    case "integer":
      return <Input {...common} inputMode="numeric" className="max-w-xs tabular" />;
    case "decimal":
    case "float":
      return <Input {...common} inputMode="decimal" className="max-w-xs tabular" />;
    case "interval":
      return (
        <Input {...common} inputMode="decimal" className="max-w-xs tabular" placeholder="seconds" />
      );
    case "date":
      return <Input {...common} type="date" className="max-w-xs" />;
    case "time":
      return <Input {...common} type="time" step={1} className="max-w-xs" />;
    case "datetime":
      return <Input {...common} type="datetime-local" step={1} className="max-w-xs" />;
    case "uuid":
      return <Input {...common} spellCheck={false} className="max-w-md font-mono text-xs" />;
    default:
      return <Input {...common} maxLength={field.max_length ?? undefined} />;
  }
}
