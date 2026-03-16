import { describe, expect, it } from "vitest";
import { validateGraph } from "../src/modules/workflows/graph-validator.js";

describe("validateGraph", () => {
  it("accepts valid graph with start and one edge", () => {
    const nodes = [
      { id: "start-1", type: "start", data: {} },
      { id: "end-1", type: "end", data: {} },
    ];
    const edges = [{ source: "start-1", target: "end-1" }];
    const result = validateGraph(nodes, edges);
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it("rejects duplicate node ids", () => {
    const nodes = [
      { id: "start-1", type: "start", data: {} },
      { id: "start-1", type: "end", data: {} },
    ];
    const edges: { source: string; target: string }[] = [];
    const result = validateGraph(nodes, edges);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.code === "duplicate_node_id")).toBe(true);
  });

  it("rejects missing start node", () => {
    const nodes = [{ id: "end-1", type: "end", data: {} }];
    const edges: { source: string; target: string }[] = [];
    const result = validateGraph(nodes, edges);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.code === "missing_start")).toBe(true);
  });

  it("rejects multiple start nodes", () => {
    const nodes = [
      { id: "start-1", type: "start", data: {} },
      { id: "start-2", type: "start", data: {} },
    ];
    const edges: { source: string; target: string }[] = [];
    const result = validateGraph(nodes, edges);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.code === "multiple_start")).toBe(true);
  });

  it("rejects edge with missing source node", () => {
    const nodes = [
      { id: "start-1", type: "start", data: {} },
      { id: "end-1", type: "end", data: {} },
    ];
    const edges = [{ source: "missing", target: "end-1" }];
    const result = validateGraph(nodes, edges);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.code === "edge_source_not_found")).toBe(true);
  });

  it("rejects edge with missing target node", () => {
    const nodes = [
      { id: "start-1", type: "start", data: {} },
      { id: "end-1", type: "end", data: {} },
    ];
    const edges = [{ source: "start-1", target: "missing" }];
    const result = validateGraph(nodes, edges);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.code === "edge_target_not_found")).toBe(true);
  });

  it("rejects invalid condition branch label", () => {
    const nodes = [
      { id: "start-1", type: "start", data: {} },
      { id: "cond-1", type: "condition", data: {} },
      { id: "end-1", type: "end", data: {} },
    ];
    const edges = [
      { source: "start-1", target: "cond-1" },
      { source: "cond-1", target: "end-1", on: "yes" },
    ];
    const result = validateGraph(nodes, edges);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.code === "invalid_branch_label")).toBe(true);
  });

  it("accepts valid condition branches true/false", () => {
    const nodes = [
      { id: "start-1", type: "start", data: {} },
      { id: "cond-1", type: "condition", data: {} },
      { id: "a", type: "end", data: {} },
      { id: "b", type: "end", data: {} },
    ];
    const edges = [
      { source: "start-1", target: "cond-1" },
      { source: "cond-1", target: "a", on: "true" },
      { source: "cond-1", target: "b", on: "false" },
    ];
    const result = validateGraph(nodes, edges);
    expect(result.valid).toBe(true);
  });

  it("rejects unknown node type", () => {
    const nodes = [
      { id: "start-1", type: "start", data: {} },
      { id: "x", type: "unknown_type", data: {} },
    ];
    const edges = [{ source: "start-1", target: "x" }];
    const result = validateGraph(nodes, edges);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.code === "unknown_node_type")).toBe(true);
  });

  it("reports unreachable node", () => {
    const nodes = [
      { id: "start-1", type: "start", data: {} },
      { id: "end-1", type: "end", data: {} },
      { id: "orphan", type: "end", data: {} },
    ];
    const edges = [{ source: "start-1", target: "end-1" }];
    const result = validateGraph(nodes, edges);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.code === "unreachable_node" && e.node_id === "orphan")).toBe(true);
  });
});
