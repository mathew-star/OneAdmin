/** What a list or detail view shows, resolved from the model schema. */
import type { FieldSchema, ModelSchema, RelationSchema } from "@/api/types";

export type Column =
  | { type: "field"; name: string; label: string; field: FieldSchema }
  | { type: "relation"; name: string; label: string; relation: RelationSchema };

/** The list's columns, in `list_display` order. Names the schema doesn't know are skipped. */
export function listColumns(model: ModelSchema): Column[] {
  return model.list_display.flatMap((name): Column[] => resolve(model, name));
}

/**
 * The detail view's rows: every field in schema order, with a foreign-key column replaced by
 * its relation (the related row's label, linked) when the admin exposes one.
 */
export function detailColumns(model: ModelSchema): Column[] {
  const byLocal = new Map(model.relations.map((r) => [r.local_field, r]));
  const shown = new Set<string>();
  const columns: Column[] = [];
  for (const field of model.fields) {
    const relation = byLocal.get(field.name);
    if (relation && !shown.has(relation.name)) {
      shown.add(relation.name);
      columns.push({ type: "relation", name: relation.name, label: relation.label, relation });
    } else if (!relation) {
      columns.push({ type: "field", name: field.name, label: field.label, field });
    }
  }
  return columns;
}

function resolve(model: ModelSchema, name: string): Column[] {
  const field = model.fields.find((f) => f.name === name);
  if (field) return [{ type: "field", name, label: field.label, field }];
  const relation = model.relations.find((r) => r.name === name);
  if (relation) return [{ type: "relation", name, label: relation.label, relation }];
  return [];
}
