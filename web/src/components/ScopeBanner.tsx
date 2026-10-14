import { useScope } from "../scope";

/** Shows the active folder scope on Search/Ask/Graph, with a one-click clear. */
export function ScopeBanner() {
  const { scope, setScope } = useScope();
  return (
    <div className="scope-banner">
      {scope ? (
        <>
          <span className="scope-label">Scoped to</span>
          <span className="scope-chip">{scope.name}</span>
          <button type="button" className="link-button" onClick={() => setScope(null)}>
            Whole repository
          </button>
        </>
      ) : (
        <span className="scope-label muted">Whole repository · set a folder scope in the Library</span>
      )}
    </div>
  );
}
