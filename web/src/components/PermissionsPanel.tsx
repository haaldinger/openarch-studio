import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Check } from "lucide-react";
import { ApiError, getAccess, putAccess } from "../api";
import { useSession } from "../session";
import { EMPTY_DRAFT, PERMISSION_LABEL, RuleEditor, draftToRule, type RuleDraft } from "./RuleEditor";
import type { AccessInfo, AccessRule, RuleInput } from "../types";

// Extra wait after an expiry so the server has archived the rule when we refetch.
const REFETCH_MARGIN_MS = 1000;

const COLUMNS: { label: string; grants: string[] }[] = [
  { label: "Read", grants: ["Read", "ReadWrite", "Everything"] },
  { label: "Write", grants: ["Write", "ReadWrite", "Everything"] },
  { label: "Manage security", grants: ["ManageSecurity", "Everything"] },
];

function clock(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

function windowParts(rule: AccessRule, now: number): string[] {
  const parts: string[] = [];
  const begin = rule.begin ? Date.parse(rule.begin) : null;
  const end = rule.end ? Date.parse(rule.end) : null;
  if (begin !== null && begin > now) parts.push(`starts in ${clock(Math.ceil((begin - now) / 1000))}`);
  if (end !== null) {
    parts.push(
      end > now ? `expires in ${clock(Math.ceil((end - now) / 1000))}` : "expired",
    );
  }
  return parts.length ? parts : ["always"];
}

function ruleToInput(rule: AccessRule): RuleInput {
  const input: RuleInput = {
    principal: { kind: rule.principal.kind, id: rule.principal.id },
    permission: rule.permission,
  };
  if (rule.begin) input.begin = rule.begin;
  if (rule.end) input.end = rule.end;
  return input;
}

/** The next moment a rule starts or ends, as epoch ms (or null when nothing is pending). */
function nextBoundary(rules: AccessRule[], now: number): number | null {
  let next: number | null = null;
  for (const r of rules) {
    for (const stamp of [r.begin, r.end]) {
      const t = stamp ? Date.parse(stamp) : NaN;
      if (t > now && (next === null || t < next)) next = t;
    }
  }
  return next;
}

export function PermissionsPanel({ docId }: { docId: string }) {
  const { generation } = useSession();
  const [data, setData] = useState<AccessInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<RuleDraft>(EMPTY_DRAFT);
  const [reloadKey, setReloadKey] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let stale = false;
    getAccess(docId)
      .then((info) => {
        if (stale) return;
        setData(info);
        setError(null);
        setNow(Date.now());
      })
      .catch((err: unknown) => {
        if (!stale) setError(err instanceof Error ? err.message : "Could not load permissions.");
      });
    return () => {
      stale = true;
    };
  }, [docId, generation, reloadKey]);

  useEffect(() => {
    setData(null);
    setDraft(EMPTY_DRAFT);
  }, [docId]);

  const rules = data?.rules ?? [];

  // Tick the countdown once a second while any rule has a future start or end.
  const ticking = nextBoundary(rules, now) !== null;
  useEffect(() => {
    if (!ticking) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [ticking]);

  // Keyed on data (not the ticking clock) so the timer survives until the boundary passes.
  useEffect(() => {
    const boundary = data ? nextBoundary(data.rules, Date.now()) : null;
    if (boundary === null) return;
    const timer = setTimeout(reload, boundary - Date.now() + REFETCH_MARGIN_MS);
    return () => clearTimeout(timer);
  }, [data, reload]);

  const local = rules.filter((r) => r.source.kind === "local");
  const inherited = rules.filter((r) => r.source.kind === "inherited");

  async function save(next: RuleInput[]) {
    setBusy(true);
    setError(null);
    try {
      setData(await putAccess(docId, next));
      setNow(Date.now());
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change access.");
      if (err instanceof ApiError && err.status === 409) reload();
      return false;
    } finally {
      setBusy(false);
    }
  }

  // Archived rules can't be re-sent (their end is in the past); dropping them is what OpenArch would do anyway.
  const sendable = (except?: AccessRule) =>
    local.filter((r) => r !== except && r.status !== "ARCHIVED").map(ruleToInput);

  async function handleAdd() {
    const rule = draftToRule(draft);
    if (!rule) return;
    if (await save([...sendable(), rule])) setDraft(EMPTY_DRAFT);
  }

  if (!data) {
    return error ? (
      <p className="form-error" role="alert">
        {error}
      </p>
    ) : (
      <p className="muted">Loading…</p>
    );
  }

  const addable = draftToRule(draft) !== null;

  return (
    <div className="perm-panel">
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <section className="perm-section">
        <h3 className="perm-heading">{data.canManage ? "Who can access" : "Your access"}</h3>
        <table className="perm-table perm-grid" aria-label="Who can access">
          <thead>
            <tr>
              <th scope="col">Person</th>
              {COLUMNS.map((c) => (
                <th key={c.label} scope="col" className="perm-check">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.effective.map((row) => (
              <tr key={row.userId ?? row.username}>
                <th scope="row">
                  <span className="perm-name">{row.username}</span>
                  {row.label && <span className="perm-sub">{row.label}</span>}
                </th>
                {COLUMNS.map((c) => (
                  <td key={c.label} className="perm-check">
                    {c.grants.some((g) => row.permissions.includes(g)) ? (
                      <Check size={16} role="img" aria-label="Yes" className="perm-yes" />
                    ) : (
                      <span aria-hidden="true" className="perm-no">
                        –
                      </span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {!data.canManage ? (
        <p className="muted perm-note">Only users with Manage security can see the rules</p>
      ) : (
        <>
          <section className="perm-section">
            <h3 className="perm-heading">Access rules</h3>
            {rules.length === 0 ? (
              <p className="muted">No rules set on this item.</p>
            ) : (
              <table className="perm-table" aria-label="Access rules">
                <thead>
                  <tr>
                    <th scope="col">Who</th>
                    <th scope="col">Permission</th>
                    <th scope="col">Granted</th>
                    <th scope="col">Window</th>
                    <th scope="col">Status</th>
                    <th scope="col">Source</th>
                    <th scope="col">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {[...local, ...inherited].map((rule, i) => {
                    const who = rule.principal.name ?? rule.principal.id;
                    return (
                      <tr key={i}>
                        <td>
                          <span className="perm-name">{who}</span>
                          {rule.principal.label && (
                            <span className="perm-sub">{rule.principal.label}</span>
                          )}
                          {rule.principal.kind === "group" && <span className="perm-sub">group</span>}
                        </td>
                        <td>{PERMISSION_LABEL[rule.permission] ?? rule.permission}</td>
                        <td>{rule.granted ? "Granted" : "Denied"}</td>
                        <td>
                          {windowParts(rule, now).map((part) => (
                            <span key={part} className="perm-window">
                              {part}
                            </span>
                          ))}
                        </td>
                        <td>
                          {rule.status ? (
                            <span className={`perm-status perm-status-${rule.status.toLowerCase()}`}>
                              {rule.status}
                            </span>
                          ) : (
                            "–"
                          )}
                        </td>
                        <td>
                          {rule.source.kind === "inherited" ? (
                            rule.source.id ? (
                              <Link to={`/documents/${rule.source.id}`}>
                                Inherited from {rule.source.title ?? rule.source.id}
                                <span aria-hidden="true"> ›</span>
                              </Link>
                            ) : (
                              `Inherited from ${rule.source.title ?? "a parent folder"}`
                            )
                          ) : (
                            "Set here"
                          )}
                        </td>
                        <td>
                          {rule.source.kind === "local" && (
                            <button
                              type="button"
                              className="btn-danger"
                              disabled={busy}
                              aria-label={`Remove ${who} ${PERMISSION_LABEL[rule.permission] ?? rule.permission}`}
                              onClick={() => void save(sendable(rule))}
                            >
                              Remove
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
            {inherited.length > 0 && (
              <p className="muted perm-note">
                To restrict one document in a shared folder, move it to a restricted folder.
              </p>
            )}
          </section>

          <section className="perm-section">
            <h3 className="perm-heading">Add rule</h3>
            <RuleEditor value={draft} onChange={setDraft} />
            <button
              type="button"
              className="btn-primary"
              disabled={busy || !addable}
              onClick={() => void handleAdd()}
            >
              Add rule
            </button>
          </section>
        </>
      )}
    </div>
  );
}
