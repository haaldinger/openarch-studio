import { createContext, useContext, useState, type ReactNode } from "react";

export interface Scope {
  id: string;
  name: string;
}

interface ScopeContextValue {
  scope: Scope | null;
  setScope: (scope: Scope | null) => void;
}

const ScopeContext = createContext<ScopeContextValue>({ scope: null, setScope: () => {} });

/** Active folder scope shared by Search, Ask, and Graph (set from the Library). */
export function ScopeProvider({ children }: { children: ReactNode }) {
  const [scope, setScope] = useState<Scope | null>(null);
  return <ScopeContext.Provider value={{ scope, setScope }}>{children}</ScopeContext.Provider>;
}

export function useScope() {
  return useContext(ScopeContext);
}
