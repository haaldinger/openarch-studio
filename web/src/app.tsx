import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { LoginPage } from "./pages/LoginPage";
import { LibraryPage } from "./pages/LibraryPage";
import { SearchPage } from "./pages/SearchPage";
import { AskPage } from "./pages/AskPage";
import { GraphPage } from "./pages/GraphPage";
import { DocumentPage } from "./pages/DocumentPage";
import { ActivityPage } from "./pages/ActivityPage";
import { CapabilityPage } from "./pages/CapabilityPage";
import { HelpPage } from "./pages/HelpPage";
import { getSession, getConfig, setConfig, logout } from "./api";
import { ScopeProvider } from "./scope";
import { SessionProvider } from "./session";
import type { SessionInfo } from "./types";

export function App() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [baselineMode, setBaselineMode] = useState(false);
  const [demoMode, setDemoMode] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const navigate = useNavigate();

  // Restore an existing server session and read runtime flags on load.
  useEffect(() => {
    Promise.all([
      getSession().catch(() => null),
      getConfig().catch(() => null),
    ])
      .then(([restored, config]) => {
        setSession(restored && normalise(restored));
        setBaselineMode(config?.baselineMode ?? false);
        setDemoMode(config?.demoMode ?? false);
      })
      .finally(() => setRestoring(false));
  }, []);

  if (restoring) {
    return <div className="boot" role="status" aria-label="Loading" />;
  }

  if (!session) {
    return (
      <LoginPage
        onAuthenticated={(info) => {
          setSession(normalise(info));
          navigate("/library");
        }}
      />
    );
  }

  async function handleSignOut() {
    try {
      await logout();
    } finally {
      setSession(null);
    }
  }

  async function handleToggleBaseline() {
    try {
      const config = await setConfig(!baselineMode);
      setBaselineMode(config.baselineMode);
    } catch {
      /* leave the current mode in place if the flip fails */
    }
  }

  return (
    <ScopeProvider>
      <SessionProvider initial={session} demoMode={demoMode}>
        <AppShell
          username={session.username}
          baselineMode={baselineMode}
          onToggleBaseline={handleToggleBaseline}
          onSignOut={handleSignOut}
        >
          <Routes>
            <Route path="/" element={<Navigate to="/library" replace />} />
            <Route path="/library" element={<LibraryPage baselineMode={baselineMode} />} />
            <Route
              path="/search"
              element={baselineMode ? <Navigate to="/library" replace /> : <SearchPage />}
            />
            <Route
              path="/ask"
              element={baselineMode ? <Navigate to="/library" replace /> : <AskPage />}
            />
            <Route
              path="/graph"
              element={baselineMode ? <Navigate to="/library" replace /> : <GraphPage />}
            />
            <Route path="/documents" element={<DocumentPage baselineMode={baselineMode} />} />
            <Route
              path="/documents/:docId"
              element={<DocumentPage baselineMode={baselineMode} />}
            />
            <Route
              path="/activity"
              element={baselineMode ? <Navigate to="/library" replace /> : <ActivityPage />}
            />
            <Route path="/capabilities" element={<CapabilityPage />} />
            <Route path="/help" element={<HelpPage />} />
            <Route path="*" element={<Navigate to="/library" replace />} />
          </Routes>
        </AppShell>
      </SessionProvider>
    </ScopeProvider>
  );
}

/** Older/partial session payloads may omit the demo fields. */
function normalise(info: Partial<SessionInfo> & { username: string }): SessionInfo {
  return { username: info.username, actingAs: info.actingAs ?? null, demoAdmin: info.demoAdmin ?? false };
}
