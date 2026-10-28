import { useState, type FormEvent } from "react";
import { ApiError, login } from "../api";
import type { SessionInfo } from "../types";

interface LoginPageProps {
  onAuthenticated: (session: SessionInfo) => void;
}

/** First impression and the only unauthenticated screen. Validates against OpenArch. */
export function LoginPage({ onAuthenticated }: LoginPageProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!username.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const session = await login(username.trim(), password);
      onAuthenticated(session);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Invalid username or password.");
      } else if (err instanceof ApiError && err.status === 503) {
        setError("OpenArch is unreachable. Is the stack running?");
      } else {
        setError("Something went wrong signing in.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <section className="login-pitch" aria-hidden="true">
        <div className="login-wordmark">
          <span className="wordmark-open">Open</span>
          <span className="wordmark-arch">Arch</span>
          <em>Studio</em>
        </div>
        <p className="login-headline">
          Watch a document become <span className="hl">AI&#8209;ready</span> — and see exactly
          which part is OpenArch.
        </p>
        <ul className="login-flow">
          <li>
            <span className="tag native">OpenArch</span> stores the file, metadata &amp; ACLs
          </li>
          <li>
            <span className="tag studio">Studio</span> extracts, chunks &amp; embeds
          </li>
          <li>
            <span className="tag model">Agent</span> answers, grounded &amp; cited
          </li>
        </ul>
      </section>

      <section className="login-form-wrap">
        <form className="login-form" onSubmit={handleSubmit}>
          <h1>Sign in</h1>
          <p className="muted">Use your OpenArch repository credentials.</p>

          <label htmlFor="username">Username</label>
          <input
            id="username"
            name="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />

          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />

          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}

          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? "Signing in\u2026" : "Enter Studio"}
          </button>
          <p className="fineprint">
            Credentials are held in server memory for the session only — never written to the
            browser.
          </p>
        </form>
      </section>
    </div>
  );
}
