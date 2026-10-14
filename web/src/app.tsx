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
import { getSession, logout } from "./api";
import { ScopeProvider } from "./scope";

export function App() {
  const [username, setUsername] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(true);
  const navigate = useNavigate();

  // Restore an existing server session on load (cookie-based).
  useEffect(() => {
    getSession()
      .then((session) => setUsername(session?.username ?? null))
      .catch(() => setUsername(null))
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

  return (
    <ScopeProvider>
      <AppShell username={username} onSignOut={handleSignOut}>
        <Routes>
          <Route path="/" element={<Navigate to="/library" replace />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/ask" element={<AskPage />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/documents" element={<DocumentPage />} />
          <Route path="/documents/:docId" element={<DocumentPage />} />
          <Route path="/activity" element={<ActivityPage />} />
          <Route path="/capabilities" element={<CapabilityPage />} />
          <Route path="/help" element={<HelpPage />} />
          <Route path="*" element={<Navigate to="/library" replace />} />
        </Routes>
      </AppShell>
    </ScopeProvider>
  );
}
