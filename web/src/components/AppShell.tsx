import { NavLink, Link, useNavigate } from "react-router-dom";
import { useState, type ReactNode } from "react";
import { HelpCircle } from "lucide-react";
import { NAV_ITEMS } from "../nav";
import { ApiError, actAs, listPersonas, resetDemo, setupDemo } from "../api";
import { useSession } from "../session";
import { Modal } from "./Modal";
import { PersonaPicker, personaName } from "./PersonaPicker";
import type { Persona } from "../types";

interface AppShellProps {
  username: string;
  onSignOut: () => void;
  children: ReactNode;
  /** Baseline (OpenArch-only) mode hides every Studio extension surface. */
  baselineMode?: boolean;
  /** Flip baseline mode live; omit to hide the switch. */
  onToggleBaseline?: () => void;
}

/** Authenticated frame: an editorial left rail, a running provenance line, and the active view. */
export function AppShell({
  username,
  onSignOut,
  children,
  baselineMode = false,
  onToggleBaseline,
}: AppShellProps) {
  const items = NAV_ITEMS.filter((item) => !baselineMode || !item.ext);
  const { session, demoMode, refresh } = useSession();
  const navigate = useNavigate();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [demoMenuOpen, setDemoMenuOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const showDemo = demoMode && session.demoAdmin;
  const origin = session.username || username;
  const actingAs = session.actingAs;
  const viewingName = personaName(actingAs?.username ?? origin);

  async function run(action: () => Promise<void>, fallback: string) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof ApiError && err.message ? err.message : fallback);
    } finally {
      setBusy(false);
    }
  }

  function switchTo(target: string) {
    setPickerOpen(false);
    return run(async () => {
      await refresh(await actAs(target));
    }, "Couldn't switch identity.");
  }

  function openPicker() {
    setPickerOpen(true);
    setError(null);
    listPersonas()
      .then(setPersonas)
      .catch(() => setError("Couldn't load the demo users."));
  }

  function handleSetup() {
    setDemoMenuOpen(false);
    return run(async () => {
      await setupDemo();
      // Setup jobs belong to the origin, so Activity must show the origin's view.
      await refresh(actingAs ? await actAs(origin) : undefined);
      navigate("/activity");
    }, "Couldn't set up the demo.");
  }

  function handleReset() {
    setResetOpen(false);
    return run(async () => {
      await resetDemo();
      await refresh();
      navigate("/library");
    }, "Couldn't reset the demo.");
  }

  const originPersona: Persona = {
    username: origin,
    label: "Your own access",
    groups: [],
    available: true,
  };
  return (
    <div className="shell">
      <a className="skip-link" href="#view">
        Skip to content
      </a>

      <aside className="rail" aria-label="Primary">
        <div className="wordmark">
          <span className="wordmark-open">Open</span>
          <span className="wordmark-arch">Arch</span>
          <em>{baselineMode ? "Baseline" : "Studio"}</em>
        </div>

        <nav className="rail-nav">
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) => (isActive ? "rail-link active" : "rail-link")}
              >
                <Icon size={19} strokeWidth={1.75} />
                <span className="rail-link-text">
                  <span className="rail-link-label">{item.label}</span>
                  <span className="rail-link-hint">{item.hint}</span>
                </span>
              </NavLink>
            );
          })}
        </nav>

        <div className="rail-foot">
          {onToggleBaseline && (
            <button
              type="button"
              role="switch"
              aria-checked={baselineMode}
              className={baselineMode ? "baseline-switch on" : "baseline-switch"}
              onClick={onToggleBaseline}
              title="Show only native OpenArch, or re-enable Studio extensions"
            >
              <span className="baseline-switch-track" aria-hidden="true">
                <span className="baseline-switch-thumb" />
              </span>
              <span className="baseline-switch-text">
                <span className="baseline-switch-label">Baseline mode</span>
                <span className="baseline-switch-state">{baselineMode ? "On · native only" : "Off · Studio on"}</span>
              </span>
            </button>
          )}
          <div className="whoami">
            <span className="whoami-dot" aria-hidden="true" />
            <span className="whoami-name">{username}</span>
          </div>
          {showDemo && (
            <>
              <button type="button" className="persona-switch" disabled={busy} onClick={openPicker}>
                Acting as: {viewingName} ▾
              </button>
              <div className="demo-menu">
                <button
                  type="button"
                  className="link-button"
                  aria-expanded={demoMenuOpen}
                  onClick={() => setDemoMenuOpen((open) => !open)}
                >
                  Demo ▾
                </button>
                {demoMenuOpen && (
                  <div className="demo-menu-items">
                    <button type="button" className="link-button" disabled={busy} onClick={handleSetup}>
                      Set up demo
                    </button>
                    <button
                      type="button"
                      className="link-button"
                      disabled={busy}
                      onClick={() => {
                        setDemoMenuOpen(false);
                        setResetOpen(true);
                      }}
                    >
                      Reset demo
                    </button>
                  </div>
                )}
              </div>
            </>
          )}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button type="button" className="link-button" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </aside>

      <div className="stage">
        {showDemo && actingAs && (
          <div className="acting-banner" role="status">
            <span>{`You're seeing what ${personaName(actingAs.username)} (${actingAs.label}) can see`}</span>
            <button type="button" className="btn-ghost" disabled={busy} onClick={() => switchTo(origin)}>
              Back to Admin
            </button>
          </div>
        )}
        {baselineMode && (
          <div className="baseline-banner" role="status">
            <strong>Baseline mode</strong> — Studio extensions are disabled. Showing native
            OpenArch out-of-the-box capabilities only.
          </div>
        )}
        <header className="provenance" aria-label="Provenance">
          {baselineMode ? (
            <span className="prov-step native">OpenArch record — native only</span>
          ) : (
            <>
              <span className="prov-step native">OpenArch record</span>
              <span className="prov-arrow" aria-hidden="true">
                →
              </span>
              <span className="prov-step studio">Studio enrichment</span>
              <span className="prov-arrow" aria-hidden="true">
                →
              </span>
              <span className="prov-step model">Grounded answer</span>
            </>
          )}
          <Link to="/help" className="prov-help" aria-label="Guide" title="Help & guide">
            <HelpCircle size={18} strokeWidth={1.75} />
          </Link>
        </header>

        <main id="view" className="view" tabIndex={-1}>
          {children}
        </main>
      </div>

      {showDemo && (
        <>
          <PersonaPicker
            open={pickerOpen}
            onClose={() => setPickerOpen(false)}
            onPick={switchTo}
            personas={[originPersona, ...personas]}
            current={actingAs?.username ?? origin}
          />
          <Modal
            open={resetOpen}
            title="Reset demo"
            onClose={() => setResetOpen(false)}
            footer={
              <>
                <button type="button" className="btn-ghost" onClick={() => setResetOpen(false)}>
                  Cancel
                </button>
                <button type="button" className="btn-danger" onClick={handleReset}>
                  Reset demo
                </button>
              </>
            }
          >
            <p className="modal-confirm">
              This deletes the four Demo folders and everything in them, then clears their search data.
            </p>
          </Modal>
        </>
      )}
    </div>
  );
}
