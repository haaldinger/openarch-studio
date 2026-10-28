import { useCallback, useState } from "react";
import { PrincipalPicker } from "./PrincipalPicker";
import type { Principal, RuleInput } from "../types";

export const PERMISSIONS = ["Read", "ReadWrite", "Write", "ManageSecurity", "Everything"] as const;

export const PERMISSION_LABEL: Record<string, string> = {
  Read: "Read",
  ReadWrite: "Read & write",
  Write: "Write",
  ManageSecurity: "Manage security",
  Everything: "Everything",
};

export type WindowKind = "none" | "2min" | "1hour" | "eod" | "custom";

const WINDOWS: { kind: WindowKind; label: string }[] = [
  { kind: "none", label: "no limit" },
  { kind: "2min", label: "2 min" },
  { kind: "1hour", label: "1 hour" },
  { kind: "eod", label: "end of day" },
  { kind: "custom", label: "custom" },
];

export interface RuleDraft {
  principal: Principal | null;
  permission: string;
  window: WindowKind;
  /** `datetime-local` value, used when window is "custom". */
  customEnd: string;
}

export const EMPTY_DRAFT: RuleDraft = {
  principal: null,
  permission: "Read",
  window: "none",
  customEnd: "",
};

/** Resolves the draft into a rule; the window is measured from `now`. Null while incomplete. */
export function draftToRule(draft: RuleDraft, now: Date = new Date()): RuleInput | null {
  if (!draft.principal) return null;
  const rule: RuleInput = {
    principal: { kind: draft.principal.kind, id: draft.principal.id },
    permission: draft.permission,
  };
  let end: Date | null = null;
  if (draft.window === "2min") end = new Date(now.getTime() + 2 * 60_000);
  else if (draft.window === "1hour") end = new Date(now.getTime() + 60 * 60_000);
  else if (draft.window === "eod") {
    end = new Date(now);
    end.setHours(23, 59, 59, 0);
  } else if (draft.window === "custom") {
    if (!draft.customEnd) return null;
    end = new Date(draft.customEnd);
    if (Number.isNaN(end.getTime())) return null;
  }
  if (end) rule.end = end.toISOString();
  return rule;
}

interface RuleEditorProps {
  value: RuleDraft;
  onChange: (next: RuleDraft) => void;
}

/** Who, what permission, and an optional time window. */
export function RuleEditor({ value, onChange }: RuleEditorProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const closePicker = useCallback(() => setPickerOpen(false), []);

  return (
    <div className="rule-editor">
      <div className="rule-field">
        <span className="rule-field-label">Who</span>
        <button type="button" className="btn-ghost" onClick={() => setPickerOpen(true)}>
          {value.principal ? (value.principal.name ?? value.principal.id) : "Choose person or group"}
        </button>
      </div>
      <div className="rule-field">
        <span className="rule-field-label">Permission</span>
        <div className="rule-chips" role="group" aria-label="Permission">
          {PERMISSIONS.map((p) => (
            <button
              key={p}
              type="button"
              className={value.permission === p ? "rule-chip active" : "rule-chip"}
              aria-pressed={value.permission === p}
              onClick={() => onChange({ ...value, permission: p })}
            >
              {PERMISSION_LABEL[p]}
            </button>
          ))}
        </div>
      </div>
      <div className="rule-field">
        <span className="rule-field-label">Access lasts</span>
        <div className="rule-chips" role="group" aria-label="Access lasts">
          {WINDOWS.map((w) => (
            <button
              key={w.kind}
              type="button"
              className={value.window === w.kind ? "rule-chip active" : "rule-chip"}
              aria-pressed={value.window === w.kind}
              onClick={() => onChange({ ...value, window: w.kind })}
            >
              {w.label}
            </button>
          ))}
        </div>
        {value.window === "custom" && (
          <input
            type="datetime-local"
            className="modal-input rule-custom"
            aria-label="Access ends"
            value={value.customEnd}
            onChange={(e) => onChange({ ...value, customEnd: e.target.value })}
          />
        )}
      </div>
      <PrincipalPicker
        open={pickerOpen}
        onClose={closePicker}
        onPick={(principal) => {
          onChange({ ...value, principal });
          setPickerOpen(false);
        }}
      />
    </div>
  );
}
