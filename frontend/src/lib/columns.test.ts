import { describe, expect, it } from "vitest";
import type { ModelSchema } from "@/api/types";
import { detailColumns, listColumns } from "./columns";

const model: ModelSchema = {
  slug: "posts",
  name: "Post",
  name_plural: "Posts",
  pk: ["id"],
  label_field: "title",
  fields: [
    {
      name: "id",
      label: "Id",
      kind: "integer",
      widget: "integer",
      nullable: false,
      primary_key: true,
      sortable: true,
      filter_ops: [],
      tz_aware: false,
      writable: false,
      required: false,
    },
    {
      name: "title",
      label: "Title",
      kind: "string",
      widget: "string",
      nullable: false,
      primary_key: false,
      sortable: true,
      filter_ops: [],
      tz_aware: false,
      writable: false,
      required: false,
    },
    {
      name: "author_id",
      label: "Author id",
      kind: "integer",
      widget: "integer",
      nullable: false,
      primary_key: false,
      sortable: true,
      filter_ops: [],
      tz_aware: false,
      writable: false,
      required: false,
    },
  ],
  relations: [{ name: "author", label: "Author", local_field: "author_id", target: "users" }],
  list_display: ["id", "title", "author", "missing"],
  list_filter: [],
  searchable: false,
  default_sort: ["-id"],
  per_page: 50,
  permissions: { view: true, add: false, change: false, delete: false },
  actions: [],
};

describe("columns", () => {
  it("resolves list_display to fields and relations, skipping unknown names", () => {
    expect(listColumns(model).map((c) => `${c.type}:${c.name}`)).toEqual([
      "field:id",
      "field:title",
      "relation:author",
    ]);
  });

  it("shows a foreign key as its relation in the detail view, in field order", () => {
    expect(detailColumns(model).map((c) => `${c.type}:${c.name}`)).toEqual([
      "field:id",
      "field:title",
      "relation:author",
    ]);
  });
});
