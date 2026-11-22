/**
 * Friendly names for the generated API types. `openapi.d.ts` is generated from the Pydantic
 * contract (`pnpm gen:api`), so these never drift from the server.
 */
import type { components } from "./openapi";

type Schemas = components["schemas"];

export type SiteSchema = Schemas["SiteSchema"];
export type ModelSchema = Schemas["ModelSchema"];
export type FieldSchema = Schemas["FieldSchema"];
export type FieldKind = FieldSchema["kind"];
export type RelationSchema = Schemas["RelationSchema"];
export type ListOut = Schemas["ListOut"];
export type RowOut = Schemas["RowOut"];
export type CountOut = Schemas["CountOut"];
export type SessionOut = Schemas["SessionOut"];
export type UserOut = Schemas["UserOut"];
export type ErrorBody = Schemas["ErrorBody"];
export type ActionSchema = Schemas["ActionSchema"];
export type ActionOut = Schemas["ActionOut"];
export type HistoryEntry = Schemas["HistoryEntry"];
export type HistoryOut = Schemas["HistoryOut"];
export type ModelPermissions = Schemas["ModelPermissions"];

/** A relation's value in a row: the target's encoded primary key and its label. */
export interface RelationValue {
  pk: string;
  /** `null` when the target row exists but is outside the viewer's scope. */
  label: string | null;
}
