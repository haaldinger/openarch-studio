import { NavLink, Link } from "react-router-dom";
import type { ReactNode } from "react";
import { HelpCircle } from "lucide-react";
import { NAV_ITEMS } from "../nav";

interface AppShellProps {
  username: string;
  onSignOut: () => void;
  children: ReactNode;
}

/** Authenticated frame: an editorial left rail, a running provenance line, and the active view. */
export function AppShell({ username, onSignOut, children }: AppShellProps) {
  return (
    <div className="shell">
      <a className="skip-link" href="#view">
        Skip to content
      </a>

      <aside className="rail" aria-label="Primary">
        <div className="wordmark">
          <span className="wordmark-open">Open</span>
          <span className="wordmark-arch">Arch</span>
          <em>Studio</em>
        </div>

        <nav className="rail-nav">
          {NAV_ITEMS.map((item) => {
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
          <div className="whoami">
            <span className="whoami-dot" aria-hidden="true" />
            <span className="whoami-name">{username}</span>
          </div>
          <button type="button" className="link-button" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </aside>

      <div className="stage">
        <header className="provenance" aria-label="Provenance">
          <span className="prov-step native">OpenArch record</span>
          <span className="prov-arrow" aria-hidden="true">
            →
          </span>
          <span className="prov-step studio">Studio enrichment</span>
          <span className="prov-arrow" aria-hidden="true">
            →
          </span>
          <span className="prov-step model">Grounded answer</span>
          <Link to="/help" className="prov-help" aria-label="Guide" title="Help & guide">
            <HelpCircle size={18} strokeWidth={1.75} />
          </Link>
        </header>

        <main id="view" className="view" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
