import { useEffect, useRef, useState } from "react";
import { Modal } from "./Modal";
import { searchPrincipals } from "../api";
import type { Principal } from "../types";

interface PrincipalPickerProps {
  open: boolean;
  onClose: () => void;
  onPick: (principal: Principal) => void;
}

const DEBOUNCE_MS = 250;

/** Searchable modal to find a user or group in OpenArch. */
export function PrincipalPicker({ open, onClose, onPick }: PrincipalPickerProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Principal[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) setQuery("");
  }, [open]);

  useEffect(() => {
    const q = query.trim();
    if (!open || !q) {
      setResults([]);
      setError(null);
      setSearched(false);
      return;
    }
    let stale = false;
    const timer = setTimeout(() => {
      searchPrincipals(q)
        .then((found) => {
          if (stale) return;
          setResults(found);
          setError(null);
          setSearched(true);
        })
        .catch((err: unknown) => {
          if (stale) return;
          setResults([]);
          setError(err instanceof Error ? err.message : "Search failed");
          setSearched(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [query, open]);

  return (
    <Modal open={open} title="Choose person or group" onClose={onClose} initialFocusRef={inputRef}>
      <input
        ref={inputRef}
        type="search"
        className="modal-input"
        placeholder="Search people or groups"
        aria-label="Search people or groups"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <ul className="persona-list">
        {results.map((p) => (
          <li key={`${p.kind}:${p.id}`}>
            <button type="button" className="persona-row" onClick={() => onPick(p)}>
              <span className="persona-name">{p.name ?? p.id}</span>
              <span className="persona-label">{p.label ?? (p.kind === "group" ? "Group" : "User")}</span>
            </button>
          </li>
        ))}
        {searched && results.length === 0 && (
          <li className="modal-hint">No one matches “{query.trim()}”.</li>
        )}
        {error && (
          <li className="form-error" role="alert">
            {error}
          </li>
        )}
      </ul>
    </Modal>
  );
}
