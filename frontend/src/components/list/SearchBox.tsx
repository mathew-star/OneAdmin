import { Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Input } from "../ui";

interface SearchBoxProps {
  /** The committed search text (from the URL). */
  value: string;
  onCommit: (value: string) => void;
  label: string;
}

const DEBOUNCE_MS = 300;

/** Search that commits after typing pauses (or on Enter), so each keystroke isn't a query. */
export function SearchBox({ value, onCommit, label }: SearchBoxProps) {
  const [draft, setDraft] = useState(value);
  const commit = useRef(onCommit);
  commit.current = onCommit;

  // The URL changed from outside (back button, "clear filters"): show it.
  useEffect(() => setDraft(value), [value]);

  useEffect(() => {
    if (draft.trim() === value) return;
    const timer = setTimeout(() => commit.current(draft), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [draft, value]);

  return (
    <search className="relative w-full min-w-48 sm:w-64">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          commit.current(draft);
        }}
      >
        <Search
          className="pointer-events-none absolute top-2 left-2.5 size-4 text-muted"
          aria-hidden="true"
        />
        <Input
          type="search"
          aria-label={label}
          placeholder="Search records..."
          maxLength={200}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          className="pl-8"
        />
      </form>
    </search>
  );
}
