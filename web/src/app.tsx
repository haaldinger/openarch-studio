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

export function App() {
  const [username, setUsername] = useState<string | null>(null);
  const [baselineMode, setBaselineMode] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const navigate = useNavigate();

  // Restore an existing server session and read runtime flags on load.
  useEffect(() => {
    Promise.all([
      getSession()
        .then((session) => session?.username ?? null)
        .catch(() => null),
      getConfig()
        .then((config) => config.baselineMode)
        .catch(() => false),
    ])
      .then(([name, baseline]) => {
        setUsername(name);
        setBaselineMode(baseline);
      })
      .finally(() => setRestoring(false));
  }, []);

  if (restoring) {
    return <div className="boot" role="status" aria-label="Loading" />;
  }

  if (!username) {
    return (
      <LoginPage
        onAuthenticated={(name) => {
          setUsername(name);
          navigate("/library");
        }}
      />
    );
  }

  async function handleSignOut() {
    try {
      await logout();
    } finally {
      setUsername(null);
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
      <AppShell
        username={username}
        baselineMode={baselineMode}
        onToggleBaseline={handleToggleBaseline}
        onSignOut={handleSignOut}
      >
        <Routes>
          <Route path="/" element={<Navigate to="/library" replace />} />
          <Route path="/library" element={<LibraryPage />} />
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
          <Route path="/documents" element={<DocumentPage />} />
          <Route path="/documents/:docId" element={<DocumentPage />} />
          <Route
            path="/activity"
            element={baselineMode ? <Navigate to="/library" replace /> : <ActivityPage />}
          />
          <Route path="/capabilities" element={<CapabilityPage />} />
          <Route path="/help" element={<HelpPage />} />
          <Route path="*" element={<Navigate to="/library" replace />} />
        </Routes>
      </AppShell>
    </ScopeProvider>
  );
}
