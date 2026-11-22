/**
 * Widgets for the field types that ship with OneAdmin beyond plain kinds:
 * `EmailField` ("email"), `URLField` ("url") and `MoneyField` ("money").
 */
import { ExternalLink } from "lucide-react";
import { Input } from "@/components/ui";
import { Value } from "@/components/Value";
import type { CellProps, InputProps, WidgetRegistry } from "./registry";

export function registerBuiltinWidgets(registry: WidgetRegistry): WidgetRegistry {
  return registry
    .registerCell("email", EmailCell)
    .registerInput("email", (props) => <TextInput {...props} type="email" autoComplete="off" />)
    .registerCell("url", UrlCell)
    .registerInput("url", (props) => <TextInput {...props} type="url" placeholder="https://" />)
    .registerCell("money", MoneyCell)
    .registerInput("money", MoneyInput);
}

function EmailCell({ field, value }: CellProps) {
  if (typeof value !== "string" || !value) return <Value kind={field.kind} value={value} />;
  return (
    <a href={`mailto:${value}`} className="text-accent hover:underline">
      {value}
    </a>
  );
}

/** Only http(s) links are clickable: a `javascript:` value is shown as text, never a link. */
function UrlCell({ field, value }: CellProps) {
  if (typeof value !== "string" || !/^https?:\/\//i.test(value)) {
    return <Value kind={field.kind} value={value} />;
  }
  return (
    <a
      href={value}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-accent hover:underline"
    >
      <span className="truncate">{value.replace(/^https?:\/\//i, "")}</span>
      <ExternalLink className="size-3 shrink-0" aria-hidden="true" />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}

export function formatMoney(value: string, currency: string, locale?: string): string {
  try {
    // Formatting the decimal *string* keeps every digit (no float rounding of money).
    return new Intl.NumberFormat(locale, { style: "currency", currency }).format(
      value as Intl.StringNumericLiteral,
    );
  } catch {
    return `${value} ${currency}`;
  }
}

function currencyOf(props: { field: { widget_options?: Record<string, unknown> | null } }): string {
  const currency = props.field.widget_options?.currency;
  return typeof currency === "string" ? currency : "USD";
}

function MoneyCell(props: CellProps) {
  const { field, value } = props;
  if (typeof value !== "string" && typeof value !== "number") {
    return <Value kind={field.kind} value={value} />;
  }
  return <span className="tabular">{formatMoney(String(value), currencyOf(props))}</span>;
}

function MoneyInput(props: InputProps) {
  const currency = currencyOf(props);
  return (
    <div className="flex max-w-xs items-center gap-2">
      <TextInput {...props} inputMode="decimal" className="tabular" />
      <span className="text-muted text-xs">{currency}</span>
    </div>
  );
}

function TextInput({
  id,
  field,
  value,
  onChange,
  errorId,
  ...rest
}: InputProps & {
  type?: string;
  autoComplete?: string;
  placeholder?: string;
  inputMode?: "decimal";
  className?: string;
}) {
  const { allowBlank: _allowBlank, ...attrs } = rest;
  return (
    <Input
      {...attrs}
      id={id}
      value={typeof value === "string" ? value : ""}
      onChange={(e) => onChange(e.target.value)}
      maxLength={field.max_length ?? undefined}
      aria-invalid={errorId ? true : undefined}
      aria-describedby={errorId}
      aria-required={field.required || undefined}
    />
  );
}
