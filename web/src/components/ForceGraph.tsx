import { useEffect, useMemo, useRef, useState } from "react";
import { ZoomIn, ZoomOut, RotateCcw } from "lucide-react";
import type { GraphEdge, GraphNode } from "../types";

const WIDTH = 820;
const HEIGHT = 560;

export const TYPE_COLOR: Record<string, string> = {
  Person: "#3b3ad6",
  Organization: "#2f5d50",
  Location: "#b4531a",
  Policy: "#7c3aed",
  Concept: "#0f766e",
  Role: "#b45309",
  Date: "#6b7280",
};

interface Pt {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

interface View {
  k: number;
  tx: number;
  ty: number;
}

interface ForceGraphProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selected: string | null;
  onSelect: (id: string | null) => void;
  /** Entity types to hide from the drawing (layout is preserved). */
  hiddenTypes?: Set<string>;
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** Dependency-free force layout with zoom, pan, node dragging, and hover focus. */
export function ForceGraph({ nodes, edges, selected, onSelect, hiddenTypes }: ForceGraphProps) {
  const pos = useRef<Map<string, Pt>>(new Map());
  const [, setTick] = useState(0);
  const [view, setView] = useState<View>({ k: 1, tx: 0, ty: 0 });
  const [hovered, setHovered] = useState<string | null>(null);

  const svgRef = useRef<SVGSVGElement>(null);
  const gRef = useRef<SVGGElement>(null);
  const simRef = useRef<number>(0);
  const alphaRef = useRef(1);
  const dragRef = useRef<string | null>(null);
  const panRef = useRef<{ x: number; y: number } | null>(null);

  // Deterministic initial placement on a circle so the first paint already has coordinates.
  useMemo(() => {
    const next = new Map<string, Pt>();
    nodes.forEach((n, i) => {
      const a = (2 * Math.PI * i) / Math.max(nodes.length, 1);
      const existing = pos.current.get(n.id);
      next.set(
        n.id,
        existing ?? { x: WIDTH / 2 + Math.cos(a) * 180, y: HEIGHT / 2 + Math.sin(a) * 180, vx: 0, vy: 0 },
      );
    });
    pos.current = next;
  }, [nodes]);

  useEffect(() => {
    const adjacency = edges.map((e) => [e.source, e.target] as const);

    function step() {
      const p = pos.current;
      const ids = [...p.keys()];
      const alpha = alphaRef.current;
      // Repulsion between all pairs.
      for (let i = 0; i < ids.length; i++) {
        for (let j = i + 1; j < ids.length; j++) {
          const a = p.get(ids[i])!;
          const b = p.get(ids[j])!;
          let dx = a.x - b.x;
          let dy = a.y - b.y;
          const d2 = dx * dx + dy * dy || 0.01;
          const f = (8000 / d2) * alpha;
          const d = Math.sqrt(d2);
          dx /= d;
          dy /= d;
          a.vx += dx * f;
          a.vy += dy * f;
          b.vx -= dx * f;
          b.vy -= dy * f;
        }
      }
      // Edge springs.
      for (const [s, t] of adjacency) {
        const a = p.get(s);
        const b = p.get(t);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const f = (d - 120) * 0.02 * alpha;
        a.vx += (dx / d) * f;
        a.vy += (dy / d) * f;
        b.vx -= (dx / d) * f;
        b.vy -= (dy / d) * f;
      }
      // Gravity to center + integrate with damping; the dragged node stays pinned.
      for (const [id, pt] of p) {
        if (id === dragRef.current) {
          pt.vx = 0;
          pt.vy = 0;
          continue;
        }
        pt.vx += (WIDTH / 2 - pt.x) * 0.01 * alpha;
        pt.vy += (HEIGHT / 2 - pt.y) * 0.01 * alpha;
        pt.vx *= 0.82;
        pt.vy *= 0.82;
        pt.x = Math.max(24, Math.min(WIDTH - 24, pt.x + pt.vx));
        pt.y = Math.max(24, Math.min(HEIGHT - 24, pt.y + pt.vy));
      }
      alphaRef.current *= 0.97;
      setTick((t) => t + 1);
      if (alphaRef.current > 0.02) simRef.current = requestAnimationFrame(step);
    }

    alphaRef.current = 1;
    cancelAnimationFrame(simRef.current);
    simRef.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(simRef.current);
  }, [nodes, edges]);

  function reheat(alpha = 0.3) {
    alphaRef.current = Math.max(alphaRef.current, alpha);
    cancelAnimationFrame(simRef.current);
    simRef.current = requestAnimationFrame(function tick() {
      setTick((t) => t + 1);
      if (alphaRef.current > 0.02) simRef.current = requestAnimationFrame(tick);
    });
  }

  // Map a screen point into the simulation's coordinate space (accounts for zoom/pan).
  function toGraph(clientX: number, clientY: number) {
    const g = gRef.current;
    const svg = svgRef.current;
    if (!g || !svg || !g.getScreenCTM) return { x: 0, y: 0 };
    const ctm = g.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const loc = pt.matrixTransform(ctm.inverse());
    return { x: loc.x, y: loc.y };
  }

  // Map a screen point into viewBox units (ignores our pan/zoom transform).
  function toViewBox(clientX: number, clientY: number) {
    const svg = svgRef.current;
    if (!svg || !svg.getScreenCTM) return { x: 0, y: 0 };
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const loc = pt.matrixTransform(ctm.inverse());
    return { x: loc.x, y: loc.y };
  }

  function zoomAround(factor: number, cx: number, cy: number) {
    setView((v) => {
      const k = clamp(v.k * factor, 0.35, 4);
      const ratio = k / v.k;
      return { k, tx: cx - (cx - v.tx) * ratio, ty: cy - (cy - v.ty) * ratio };
    });
  }

  function onWheel(e: React.WheelEvent) {
    e.preventDefault();
    const anchor = toViewBox(e.clientX, e.clientY);
    zoomAround(e.deltaY < 0 ? 1.12 : 1 / 1.12, anchor.x, anchor.y);
  }

  function onBackgroundPointerDown(e: React.PointerEvent) {
    panRef.current = toViewBox(e.clientX, e.clientY);
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
  }

  function onNodePointerDown(e: React.PointerEvent, id: string) {
    e.stopPropagation();
    dragRef.current = id;
    reheat(0.2);
  }

  function onPointerMove(e: React.PointerEvent) {
    if (dragRef.current) {
      const g = toGraph(e.clientX, e.clientY);
      const pt = pos.current.get(dragRef.current);
      if (pt) {
        pt.x = g.x;
        pt.y = g.y;
        pt.vx = 0;
        pt.vy = 0;
        setTick((t) => t + 1);
      }
      return;
    }
    if (panRef.current) {
      const cur = toViewBox(e.clientX, e.clientY);
      const dx = cur.x - panRef.current.x;
      const dy = cur.y - panRef.current.y;
      panRef.current = cur;
      setView((v) => ({ ...v, tx: v.tx + dx, ty: v.ty + dy }));
    }
  }

  function endInteraction() {
    if (dragRef.current) reheat(0.2);
    dragRef.current = null;
    panRef.current = null;
  }

  const focus = selected ?? hovered;
  const neighbors = useMemo(() => {
    if (!focus) return null;
    const set = new Set<string>([focus]);
    edges.forEach((e) => {
      if (e.source === focus) set.add(e.target);
      if (e.target === focus) set.add(e.source);
    });
    return set;
  }, [focus, edges]);

  // Node degree drives size and which labels show, so hubs (vendors) stand out.
  const degree = useMemo(() => {
    const d = new Map<string, number>();
    edges.forEach((e) => {
      d.set(e.source, (d.get(e.source) ?? 0) + 1);
      d.set(e.target, (d.get(e.target) ?? 0) + 1);
    });
    return d;
  }, [edges]);

  const typeOf = useMemo(() => {
    const m = new Map<string, string>();
    nodes.forEach((n) => m.set(n.id, n.type));
    return m;
  }, [nodes]);

  const isHidden = (type: string) => hiddenTypes?.has(type) ?? false;
  const visibleCount = nodes.filter((n) => !isHidden(n.type)).length;
  const p = pos.current;

  return (
    <>
      <div className="graph-controls">
        <button type="button" aria-label="Zoom in" onClick={() => zoomAround(1.2, WIDTH / 2, HEIGHT / 2)}>
          <ZoomIn size={16} />
        </button>
        <button type="button" aria-label="Zoom out" onClick={() => zoomAround(1 / 1.2, WIDTH / 2, HEIGHT / 2)}>
          <ZoomOut size={16} />
        </button>
        <button type="button" aria-label="Reset view" onClick={() => setView({ k: 1, tx: 0, ty: 0 })}>
          <RotateCcw size={15} />
        </button>
      </div>
      <svg
        ref={svgRef}
        className="graph-svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label="Knowledge graph"
        onWheel={onWheel}
        onPointerDown={onBackgroundPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endInteraction}
        onPointerLeave={endInteraction}
      >
        <g ref={gRef} transform={`translate(${view.tx},${view.ty}) scale(${view.k})`}>
          {edges.map((e, i) => {
            const a = p.get(e.source);
            const b = p.get(e.target);
            if (!a || !b) return null;
            if (isHidden(typeOf.get(e.source) ?? "") || isHidden(typeOf.get(e.target) ?? "")) return null;
            const dim = neighbors && !(neighbors.has(e.source) && neighbors.has(e.target));
            const cls = `graph-edge${e.inferred ? " inferred" : ""}${dim ? " dim" : ""}`;
            return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className={cls} />;
          })}
          {nodes.map((n) => {
            const pt = p.get(n.id);
            if (!pt || isHidden(n.type)) return null;
            const dim = neighbors && !neighbors.has(n.id);
            const color = TYPE_COLOR[n.type] ?? "#6b7280";
            const deg = degree.get(n.id) ?? 0;
            const r = (selected === n.id ? 4 : 0) + 6 + Math.min(deg, 8);
            // Declutter large graphs: label hubs + focus; small graphs show every label.
            const showLabel =
              focus === n.id ||
              (neighbors?.has(n.id) ?? false) ||
              (!focus && (visibleCount <= 30 || deg >= 3));
            return (
              <g
                key={n.id}
                className={dim ? "graph-node dim" : "graph-node"}
                transform={`translate(${pt.x},${pt.y})`}
                onPointerDown={(e) => onNodePointerDown(e, n.id)}
                onClick={() => onSelect(selected === n.id ? null : n.id)}
                onMouseEnter={() => setHovered(n.id)}
                onMouseLeave={() => setHovered(null)}
              >
                <circle r={r} fill={color} />
                {showLabel && (
                  <text x={r + 4} y={4}>
                    {n.label}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>
    </>
  );
}
