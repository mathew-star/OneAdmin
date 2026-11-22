/**
 * Pick a related row by its label: an ARIA combobox over the *target* model's list
 * endpoint. Results come through the target admin's `get_queryset`, so you can only pick
 * rows you are allowed to see (the server checks again on save).
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronsUpDown, X } from "lucide-react";
import { type KeyboardEvent, useEffect, useId, useState } from "react";
import { rowPath } from "@/api/queries";
import type { ListOut, ModelSchema } from "@/api/types";
import { cx, useApp } from "@/lib/app";
import { inputClass } from "../ui";

interface RelationPickerProps {
  id: string;
  target: ModelSchema;
  /** The selected key (draft), `""` for none. */
  value: string;
  /** The label of the initially selected row, if known. */
  initialLabel: string | null;
  nullable: boolean;
  onChange: (pk: string) => void;
  errorId?: string | undefined;
}

const PAGE = 20;

export function RelationPicker({
  id,
  target,
  value,
  initialLabel,
  nullable,
  onChange,
  errorId,
}: RelationPickerProps) {
  const { client } = useApp();
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [active, setActive] = useState(0);
  const [label, setLabel] = useState<string | null>(initialLabel);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(timer);
  }, [query]);

  const options = useQuery({
    queryKey: ["picker", target.slug, debounced],
    queryFn: ({ signal }) =>
      client.get<ListOut>(
        rowPath(target.slug),
        {
          q: target.searchable && debounced ? debounced : undefined,
          limit: String(PAGE),
          count: "false",
        },
        signal,
      ),
    enabled: open,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });

  const rows = options.data?.rows ?? [];
  const labelOf = (values: Record<string, unknown>, pk: string) => {
    const raw = values[target.label_field];
    return raw === null || raw === undefined || typeof raw === "object" ? `#${pk}` : String(raw);
  };

  const choose = (pk: string, text: string) => {
    onChange(pk);
    setLabel(text);
    setQuery("");
    setOpen(false);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((i) => (rows.length ? (i + step + rows.length) % rows.length : 0));
    } else if (event.key === "Enter" && open && rows[active]) {
      event.preventDefault();
      const row = rows[active];
      choose(row.pk, labelOf(row.values, row.pk));
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
    }
  };

  const shown = open ? query : value ? (label ?? `#${value}`) : "";
  const optionId = (i: number) => `${listId}-${i}`;

  return (
    <div className="relative max-w-md">
      <input
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && rows[active] ? optionId(active) : undefined}
        aria-invalid={errorId ? true : undefined}
        aria-describedby={errorId}
        autoComplete="off"
        placeholder={target.searchable ? `Search ${target.name_plural.toLowerCase()}` : "Choose…"}
        value={shown}
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={onKeyDown}
        className={cx(inputClass, "pr-14")}
      />
      <div className="absolute top-1.5 right-1.5 flex items-center gap-0.5">
        {nullable && value ? (
          <button
            type="button"
            onClick={() => choose("", "")}
            className="rounded p-0.5 text-muted hover:text-fg"
            aria-label="Clear selection"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        ) : null}
        <ChevronsUpDown className="size-4 text-muted" aria-hidden="true" />
      </div>
      {open ? (
        <div
          id={listId}
          role="listbox"
          aria-label={target.name_plural}
          className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-border bg-surface py-1 shadow-lg"
        >
          {rows.length === 0 ? (
            <li className="px-3 py-2 text-muted">
              {options.isFetching ? "Searching…" : "No matches"}
            </li>
          ) : (
            rows.map((row, i) => (
              // WAI-ARIA combobox pattern: focus stays in the input, which drives the options
              // through aria-activedescendant, so options are neither focusable nor keyed.
              // biome-ignore lint/a11y/useFocusableInteractive: see above
              // biome-ignore lint/a11y/useKeyWithClickEvents: see above
              <div
                key={row.pk}
                id={optionId(i)}
                role="option"
                aria-selected={row.pk === value}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(row.pk, labelOf(row.values, row.pk))}
                className={cx(
                  "cursor-pointer px-3 py-1.5",
                  i === active && "bg-accent-soft",
                  row.pk === value && "font-medium",
                )}
              >
                {labelOf(row.values, row.pk)}
                <span className="ml-2 text-muted text-xs">#{row.pk}</span>
              </div>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
