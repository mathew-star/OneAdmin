/**
 * Widgets: how a field is displayed (cell) and edited (input), keyed by the field's
 * `widget` from the schema (ADR-0020). The server's `FieldType` picks the key, so a Python
 * `MoneyField("EUR")` arrives as `widget: "money"` with `{currency: "EUR"}`.
 *
 * Unknown keys fall back to the built-in rendering for the field's `kind`, so a server
 * with a newer or custom type never breaks an older UI.
 *
 * One registry per app (in the router context), never a module global: two admin apps on
 * one page, or two tests, can't affect each other.
 */
import type { ComponentType } from "react";
import type { FieldSchema } from "@/api/types";
import type { Draft } from "@/lib/formValues";

export interface CellProps {
  field: FieldSchema;
  value: unknown;
  /** Detail views show long values in full; lists truncate them. */
  full: boolean;
}

export interface InputProps {
  id: string;
  field: FieldSchema;
  value: Draft;
  onChange: (value: Draft) => void;
  /** `id` of the element describing the current error, if any. */
  errorId?: string | undefined;
  /** Offer an empty choice (nullable columns, or blank on create). */
  allowBlank: boolean;
}

export class WidgetRegistry {
  private readonly cells = new Map<string, ComponentType<CellProps>>();
  private readonly inputs = new Map<string, ComponentType<InputProps>>();

  /** Render values of fields with `widget === key`. Replaces an earlier registration. */
  registerCell(key: string, component: ComponentType<CellProps>): this {
    this.cells.set(key, component);
    return this;
  }

  /** Edit values of fields with `widget === key`. Replaces an earlier registration. */
  registerInput(key: string, component: ComponentType<InputProps>): this {
    this.inputs.set(key, component);
    return this;
  }

  /** The cell for this field, or `null` for the built-in rendering of its kind. */
  cell(field: FieldSchema): ComponentType<CellProps> | null {
    return this.cells.get(field.widget) ?? null;
  }

  input(field: FieldSchema): ComponentType<InputProps> | null {
    return this.inputs.get(field.widget) ?? null;
  }
}
