import { z } from "zod";
import { invoke } from "@tauri-apps/api/core";
import { isTauri } from "../app/native";

export const graphNodeSchema = z.object({
  id: z.string(),
  kind: z.enum(["page", "feature", "entity", "integration", "role", "workflow", "step"]),
  title: z.string(),
  description: z.string(),
  parentId: z.string().nullable(),
  position: z.object({ x: z.number(), y: z.number() }),
  details: z.record(z.unknown()),
});
export const projectGraphSchema = z.object({
  schemaVersion: z.literal(1),
  revision: z.number().int(),
  planHash: z.string(),
  title: z.string(),
  nodes: z.array(graphNodeSchema),
  edges: z.array(
    z.object({
      id: z.string(),
      source: z.string(),
      target: z.string(),
      relation: z.string(),
      label: z.string(),
      basis: z.enum(["declared", "text_reference", "proposed"]),
    }),
  ),
  enriched: z.boolean(),
  unresolvedFeatures: z.array(z.string()),
  executable: z.literal(false),
});
export type ProjectGraph = z.infer<typeof projectGraphSchema>;
export type GraphNode = z.infer<typeof graphNodeSchema>;
export const projectConnectionSchema = z.object({
  endpointPath: z.string(),
  token: z.string(),
  expiresAt: z.string(),
  readOnly: z.literal(true),
});
export type ProjectConnection = z.infer<typeof projectConnectionSchema> & { endpoint?: string };

export const KIND_LABELS: Record<GraphNode["kind"], string> = {
  page: "صفحة",
  feature: "ميزة",
  entity: "بيانات",
  integration: "ربط خارجي",
  role: "صلاحية",
  workflow: "مسار عمل",
  step: "خطوة",
};
export const KIND_COLORS: Record<GraphNode["kind"], string> = {
  page: "#5b63f0",
  feature: "#b03c75",
  entity: "#2096ad",
  integration: "#b37b18",
  role: "#65748e",
  workflow: "#28885c",
  step: "#8170ca",
};

export function relatedNodes(graph: ProjectGraph, id: string): Set<string> {
  return new Set([
    id,
    ...graph.edges.filter((e) => e.source === id || e.target === id).flatMap((e) => [e.source, e.target]),
  ]);
}

export function n8nExport(graph: ProjectGraph) {
  const names = new Map(graph.nodes.map((n, i) => [n.id, `${i + 1} · ${KIND_LABELS[n.kind]} · ${n.title}`]));
  const connections: Record<string, { main: { node: string; type: "main"; index: number }[][] }> = {};
  for (const edge of graph.edges) {
    const from = names.get(edge.source),
      to = names.get(edge.target);
    if (!from || !to) continue;
    const main = connections[from]?.main[0] ?? [];
    connections[from] = { main: [main] };
    main.push({ node: to, type: "main", index: 0 });
  }
  return {
    name: `FINORA · ${graph.title}`,
    active: false,
    settings: { executionOrder: "v1" },
    pinData: {},
    connections,
    nodes: graph.nodes.map((n) => ({
      id: n.id,
      name: names.get(n.id),
      type: "n8n-nodes-base.noOp",
      typeVersion: 1,
      position: [n.position.x, n.position.y],
      parameters: {},
      disabled: true,
      notesInFlow: true,
      notes: `${n.description}\n\n${JSON.stringify(n.details, null, 2)}\n\n${graph.edges
        .filter((e) => e.source === n.id)
        .map((e) => `${e.label} → ${names.get(e.target)}${e.basis === "proposed" ? " (اقتراح)" : ""}`)
        .join("\n")}`,
    })),
    meta: {
      finora: {
        schemaVersion: 1,
        revision: graph.revision,
        planHash: graph.planHash,
        executable: false,
        description: "خريطة مواصفات، تحتاج بناء التكاملات قبل التشغيل",
      },
    },
  };
}

function escapeXml(s: string): string {
  return s.replace(
    /[<>&"']/g,
    (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&apos;" })[c] ?? c,
  );
}

export function svgExport(graph: ProjectGraph): string {
  const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
  const minX = Math.min(0, ...graph.nodes.map((n) => n.position.x)) - 40;
  const minY = Math.min(0, ...graph.nodes.map((n) => n.position.y)) - 65;
  const width = Math.max(700, ...graph.nodes.map((n) => n.position.x + 320)) - minX;
  const height = Math.max(220, ...graph.nodes.map((n) => n.position.y + 150)) - minY;
  const edges = graph.edges
    .map((e) => {
      const a = nodes.get(e.source),
        b = nodes.get(e.target);
      if (!a || !b) return "";
      const x1 = a.position.x + 260,
        y1 = a.position.y + 46,
        x2 = b.position.x,
        y2 = b.position.y + 46;
      return `<path d="M${x1},${y1} C${x1 + 90},${y1} ${x2 - 90},${y2} ${x2},${y2}" fill="none" stroke="${e.basis === "proposed" ? "#c393af" : "#c4c7e3"}" stroke-width="2" ${e.basis !== "declared" ? 'stroke-dasharray="6 5"' : ""}><title>${escapeXml(e.label)}</title></path>`;
    })
    .join("");
  const shapes = graph.nodes
    .map(
      (n) =>
        `<g transform="translate(${n.position.x},${n.position.y})"><rect width="260" height="96" rx="16" fill="white" stroke="${KIND_COLORS[n.kind]}"/><text x="244" y="27" text-anchor="end" font-size="12" fill="${KIND_COLORS[n.kind]}">${KIND_LABELS[n.kind]}</text><text x="244" y="58" text-anchor="end" font-size="14" fill="#161833">${escapeXml(n.title.slice(0, 35))}</text><title>${escapeXml(n.title + "\n" + n.description)}</title></g>`,
    )
    .join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${minX} ${minY} ${width} ${height}" width="${width}" height="${height}" font-family="Arial, sans-serif"><rect x="${minX}" y="${minY}" width="${width}" height="${height}" fill="#f7f8fc"/><text x="${minX + width - 30}" y="${minY + 32}" text-anchor="end" fill="#4a0a24" font-size="22">${escapeXml(graph.title)} · نسخة ${graph.revision}</text>${edges}${shapes}</svg>`;
}

export async function downloadGraph(graph: ProjectGraph, format: "json" | "n8n" | "svg"): Promise<boolean> {
  const value =
    format === "svg"
      ? svgExport(graph)
      : JSON.stringify(format === "n8n" ? n8nExport(graph) : graph, null, 2);
  if (isTauri())
    return invoke<boolean>("save_project_export", { revision: graph.revision, format, content: value });
  const blob = new Blob([value], {
    type: format === "svg" ? "image/svg+xml;charset=utf-8" : "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `finora-project-${graph.revision}-${format}.${format === "svg" ? "svg" : "json"}`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  return true;
}
