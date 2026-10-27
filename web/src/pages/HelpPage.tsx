import { Link } from "react-router-dom";
import {
  LayoutGrid,
  Search,
  MessagesSquare,
  Share2,
  FileStack,
  Activity,
  Layers,
  FolderTree,
  Upload,
  Sparkles,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { PageIntro } from "../components/PageIntro";

interface FeatureHelp {
  icon: LucideIcon;
  title: string;
  to: string;
  body: string;
}

const STEPS: { icon: LucideIcon; title: string; body: string }[] = [
  {
    icon: Upload,
    title: "1 · Upload",
    body: "Drop a file into the Library — a PDF, an Office doc, a scanned image. OpenArch stores the original bytes and its permissions.",
  },
  {
    icon: Sparkles,
    title: "2 · Enrich",
    body: "Studio extracts text (OCR for scans), chunks it, embeds each chunk, and writes the vectors back into OpenArch. Watch it on Activity.",
  },
  {
    icon: MessagesSquare,
    title: "3 · Ask",
    body: "Search or ask questions. Answers are built only from chunks you're permitted to read, and every answer cites its sources.",
  },
];

const FEATURES: FeatureHelp[] = [
  {
    icon: LayoutGrid,
    title: "Library",
    to: "/library",
    body: "Upload and browse documents. Create folders, open them via the breadcrumb, and upload straight into the folder you're viewing.",
  },
  {
    icon: Search,
    title: "Search",
    to: "/search",
    body: "Three modes in one place: keyword (literal terms), semantic (meaning / vector), and raw HXQL for advanced queries. Each result shows which layer produced it.",
  },
  {
    icon: MessagesSquare,
    title: "Ask",
    to: "/ask",
    body: "A grounded chat agent. It retrieves permitted chunks, re-checks your access, then answers with citations you can open. No evidence → it says so instead of guessing.",
  },
  {
    icon: Share2,
    title: "Graph",
    to: "/graph",
    body: "A knowledge graph of entities (people, organizations, locations…) and relations a local model pulled from your enriched text. Shows only what you can read.",
  },
  {
    icon: FileStack,
    title: "Documents",
    to: "/documents",
    body: "Inspect one record: metadata, effective permissions, inline viewer, the stored embedding vectors, and the raw JSON. Delete from here too.",
  },
  {
    icon: Activity,
    title: "Activity",
    to: "/activity",
    body: "Live enrichment jobs, stage by stage: stored → extracted → chunked → embedded → indexed → classified. Retry a job if a step fails.",
  },
  {
    icon: Layers,
    title: "Capabilities",
    to: "/capabilities",
    body: "The honest ledger: what OpenArch provides natively vs. what this POC adds on top. Studio never claims the platform's work as its own.",
  },
];

const KNOW: { icon: LucideIcon; title: string; body: string }[] = [
  {
    icon: ShieldCheck,
    title: "Your permissions always apply",
    body: "Studio holds your OpenArch credentials in server memory for the session only — never in the browser. Every search, answer, and graph runs as you, so OpenArch ACLs are always enforced.",
  },
  {
    icon: FolderTree,
    title: "Scope to a folder",
    body: "On Library, open a folder and choose “Scope to this folder.” Search, Ask, and Graph then stay inside that subtree — a simple way to silo one project's content.",
  },
  {
    icon: Sparkles,
    title: "Deleting cleans up everything",
    body: "Delete a document and its embeddings go with it (they're child records in OpenArch), so it disappears from search, chat, and the graph automatically.",
  },
];

export function HelpPage() {
  return (
    <>
      <PageIntro
        eyebrow="Help"
        title="How OpenArch Studio works"
        lede="Studio puts a UI and an AI pipeline on top of OpenArch. Upload a document, watch it become AI-ready, then search, ask, and explore — always within your permissions."
      />

      <section className="help-section">
        <h2 className="help-h">Get started in three steps</h2>
        <div className="help-steps">
          {STEPS.map(({ icon: Icon, title, body }) => (
            <div className="help-step" key={title}>
              <Icon size={20} aria-hidden="true" />
              <h3>{title}</h3>
              <p>{body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="help-section">
        <h2 className="help-h">What each view does</h2>
        <div className="help-cards">
          {FEATURES.map(({ icon: Icon, title, to, body }) => (
            <Link className="help-card" to={to} key={to}>
              <span className="help-card-head">
                <Icon size={18} aria-hidden="true" />
                <h3>{title}</h3>
              </span>
              <p>{body}</p>
            </Link>
          ))}
        </div>
      </section>

      <section className="help-section">
        <h2 className="help-h">Good to know</h2>
        <div className="help-cards">
          {KNOW.map(({ icon: Icon, title, body }) => (
            <div className="help-card help-card-static" key={title}>
              <span className="help-card-head">
                <Icon size={18} aria-hidden="true" />
                <h3>{title}</h3>
              </span>
              <p>{body}</p>
            </div>
          ))}
        </div>
      </section>

      <aside className="aside-note">
        <h2>Native vs. added</h2>
        <p className="muted">
          A core goal of this POC is making it obvious which behavior is OpenArch and which is
          Studio. The <Link to="/capabilities">Capabilities</Link> view lays that out side by side.
          For the full architecture, see the technical deep dive in{" "}
          <code>pocs/openarch-studio/docs/TECHNICAL-DEEP-DIVE.md</code>.
        </p>
      </aside>
    </>
  );
}
