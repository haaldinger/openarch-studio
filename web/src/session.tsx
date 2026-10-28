import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { getSession } from "./api";
import type { SessionInfo } from "./types";

interface SessionContextValue {
  session: SessionInfo;
  demoMode: boolean;
  /** Re-read the session (or adopt `next`) and bump `generation` so pages reload. */
  refresh: (next?: SessionInfo) => Promise<void>;
  /** Increments on every identity change; include it in data-loading effect deps. */
  generation: number;
}

const DEFAULT: SessionContextValue = {
  session: { username: "", actingAs: null, demoAdmin: false },
  demoMode: false,
  refresh: async () => {},
  generation: 0,
};

const SessionContext = createContext<SessionContextValue>(DEFAULT);

export function SessionProvider({
  initial,
  demoMode,
  children,
}: {
  initial: SessionInfo;
  demoMode: boolean;
  children: ReactNode;
}) {
  const [session, setSession] = useState(initial);
  const [generation, setGeneration] = useState(0);

  const refresh = useCallback(async (next?: SessionInfo) => {
    const fresh = next ?? (await getSession());
    if (!fresh) return;
    setSession(fresh);
    setGeneration((g) => g + 1);
  }, []);

  const value = useMemo(
    () => ({ session, demoMode, refresh, generation }),
    [session, demoMode, refresh, generation],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  return useContext(SessionContext);
}
