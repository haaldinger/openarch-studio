import { useEffect, useRef, useState } from "react";
import { Modal } from "./Modal";
import type { Persona } from "../types";

interface PersonaPickerProps {
  open: boolean;
  onClose: () => void;
  onPick: (username: string) => void;
  personas: Persona[];
  /** Username currently being viewed as. */
  current: string;
}

export function personaName(username: string): string {
  return username.charAt(0).toUpperCase() + username.slice(1);
}

/** Searchable modal list of identities to view Studio as. */
export function PersonaPicker({ open, onClose, onPick, personas, current }: PersonaPickerProps) {
  const [filter, setFilter] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) setFilter("");
  }, [open]);

  const needle = filter.trim().toLowerCase();
  const visible = personas.filter((p) =>
    [p.username, p.label, ...p.groups].some((text) => text.toLowerCase().includes(needle)),
  );

  return (
    <Modal open={open} title="Act as" onClose={onClose} initialFocusRef={inputRef}>
      <input
        ref={inputRef}
        type="search"
        className="modal-input"
        placeholder="Search people or groups"
        aria-label="Search people or groups"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      <ul className="persona-list">
        {visible.map((p) => (
          <li key={p.username}>
            <button
              type="button"
              className={p.username === current ? "persona-row current" : "persona-row"}
              disabled={!p.available}
              aria-current={p.username === current ? "true" : undefined}
              title={p.available ? undefined : "Unavailable: check the demo users file"}
              onClick={() => onPick(p.username)}
            >
              <span className="persona-name">{personaName(p.username)}</span>
              <span className="persona-label">{p.label}</span>
              {p.groups.length > 0 && <span className="persona-groups">{p.groups.join(", ")}</span>}
            </button>
          </li>
        ))}
        {visible.length === 0 && <li className="modal-hint">No one matches “{filter}”.</li>}
      </ul>
    </Modal>
  );
}
