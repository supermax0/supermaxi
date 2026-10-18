import { describe, expect, it, vi } from "vitest";
const nativeInvoke = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke: nativeInvoke }));
import { downloadGraph, n8nExport, relatedNodes, svgExport, type ProjectGraph } from "./projectGraph";

export const sampleGraph: ProjectGraph = {
  schemaVersion: 1,
  revision: 2,
  planHash: "abc",
  title: "متجر الملابس",
  enriched: true,
  unresolvedFeatures: [],
  executable: false,
  nodes: [
    {
      id: "page:products",
      kind: "page",
      title: "المنتجات",
      description: "عرض الملابس ومقاساتها",
      parentId: null,
      position: { x: 0, y: 0 },
      details: { roles: ["عميل"], acceptance: ["يعرض المخزون الصحيح"] },
    },
    {
      id: "feature:products:0",
      kind: "feature",
      title: "اختيار المقاس",
      description: "يختار العميل المقاس المتاح",
      parentId: "page:products",
      position: { x: 350, y: 0 },
      details: { page: "المنتجات", roles: ["عميل"] },
    },
    {
      id: "entity:stock",
      kind: "entity",
      title: "المخزون",
      description: "كمية لكل مقاس ولون",
      parentId: null,
      position: { x: 700, y: 0 },
      details: { fields: ["الكمية", "المقاس"] },
    },
    {
      id: "workflow:buy",
      kind: "workflow",
      title: "إكمال الطلب",
      description: "يريد العميل شراء قطعة",
      parentId: null,
      position: { x: 0, y: 200 },
      details: {},
    },
    {
      id: "step:buy:choose",
      kind: "step",
      title: "يختار القطعة",
      description: "قطعة متاحة",
      parentId: "workflow:buy",
      position: { x: 350, y: 200 },
      details: { role: "عميل" },
    },
    {
      id: "step:buy:finish",
      kind: "step",
      title: "يؤكد الطلب",
      description: "طلب محفوظ",
      parentId: "workflow:buy",
      position: { x: 700, y: 200 },
      details: { terminal: true },
    },
  ],
  edges: [
    {
      id: "e1",
      source: "page:products",
      target: "feature:products:0",
      relation: "contains",
      label: "تحتوي على",
      basis: "declared",
    },
    {
      id: "e2",
      source: "feature:products:0",
      target: "entity:stock",
      relation: "uses_data",
      label: "يتحقق من مخزون المقاس",
      basis: "proposed",
    },
    {
      id: "e3",
      source: "workflow:buy",
      target: "step:buy:choose",
      relation: "starts",
      label: "بداية",
      basis: "declared",
    },
    {
      id: "e4",
      source: "step:buy:choose",
      target: "step:buy:finish",
      relation: "transition",
      label: "لديه حساب والمقاس متاح",
      basis: "declared",
    },
  ],
};

describe("project graph exports", () => {
  it("preserves every connection and uses inactive no-operation n8n nodes", () => {
    const result = n8nExport(sampleGraph);
    expect(result.active).toBe(false);
    expect(
      result.nodes.every((n) => n.disabled && n.type === "n8n-nodes-base.noOp" && !("credentials" in n)),
    ).toBe(true);
    const links = Object.values(result.connections).flatMap((c) => c.main.flat());
    expect(links).toHaveLength(sampleGraph.edges.length);
    const names = new Set(result.nodes.map((n) => n.name));
    expect(links.every((l) => names.has(l.node))).toBe(true);
    expect(result.nodes[1]?.notes).toContain("يتحقق من مخزون المقاس");
    expect(relatedNodes(sampleGraph, "feature:products:0")).toEqual(
      new Set(["feature:products:0", "page:products", "entity:stock"]),
    );
  });
  it("produces valid standalone SVG and escapes hostile project text", () => {
    const hostile = structuredClone(sampleGraph);
    hostile.title = '<script>alert("x")</script>';
    const first = hostile.nodes[0];
    if (!first) throw new Error("Fixture requires a page");
    first.description = "</title><script>run()</script>";
    const output = svgExport(hostile);
    const parsed = new DOMParser().parseFromString(output, "image/svg+xml");
    expect(parsed.querySelector("parsererror")).toBeNull();
    expect(parsed.querySelector("script")).toBeNull();
    expect(parsed.querySelectorAll("path")).toHaveLength(hostile.edges.length);
    expect(parsed.querySelector("text")?.textContent).toContain(hostile.title);
  });
  it("returns native cancellation and errors without claiming a saved file", async () => {
    vi.stubGlobal("__TAURI_INTERNALS__", {});
    const spy = nativeInvoke.mockResolvedValueOnce(false).mockRejectedValueOnce(new Error("disk error"));
    expect(await downloadGraph(sampleGraph, "n8n")).toBe(false);
    expect(spy).toHaveBeenCalledWith(
      "save_project_export",
      expect.objectContaining({ revision: 2, format: "n8n" }),
    );
    await expect(downloadGraph(sampleGraph, "svg")).rejects.toThrow("disk error");
    spy.mockReset();
    vi.unstubAllGlobals();
  });
});
