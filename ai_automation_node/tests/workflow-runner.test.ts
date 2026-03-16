import { describe, expect, it } from "vitest";
import {
  compileGraph,
  nextNodeId,
  WorkflowRunError,
  type NodeDef,
  type EdgeDef,
  type CompiledGraph,
} from "../src/modules/workflows/workflow-runner.js";

describe("compileGraph", () => {
  it("returns entryNodeId from start node", () => {
    const nodes: NodeDef[] = [
      { id: "s1", type: "start", data: {} },
      { id: "e1", type: "end", data: {} },
    ];
    const edges: EdgeDef[] = [{ source: "s1", target: "e1" }];
    const compiled = compileGraph({ nodes, edges });
    expect(compiled.entryNodeId).toBe("s1");
    expect(compiled.nodeMap.size).toBe(2);
    expect(compiled.nextMap.get("s1")).toEqual([{ target: "e1" }]);
  });

  it("throws WorkflowRunError when no start node", () => {
    const nodes: NodeDef[] = [{ id: "e1", type: "end", data: {} }];
    const edges: EdgeDef[] = [];
    expect(() => compileGraph({ nodes, edges })).toThrow(WorkflowRunError);
    try {
      compileGraph({ nodes, edges });
    } catch (e) {
      expect((e as WorkflowRunError).code).toBe("NO_START_NODE");
    }
  });

  it("throws when nodes is empty", () => {
    expect(() => compileGraph({ nodes: [], edges: [] })).toThrow(WorkflowRunError);
  });

  it("builds deterministic nextMap for condition branches", () => {
    const nodes: NodeDef[] = [
      { id: "s1", type: "start", data: {} },
      { id: "c1", type: "condition", data: {} },
      { id: "a", type: "end", data: {} },
      { id: "b", type: "end", data: {} },
    ];
    const edges: EdgeDef[] = [
      { source: "s1", target: "c1" },
      { source: "c1", target: "a", on: "true" },
      { source: "c1", target: "b", on: "false" },
    ];
    const compiled = compileGraph({ nodes, edges });
    const next = compiled.nextMap.get("c1") ?? [];
    expect(next).toHaveLength(2);
    expect(next.find((x) => x.on === "true")?.target).toBe("a");
    expect(next.find((x) => x.on === "false")?.target).toBe("b");
  });
});

describe("nextNodeId", () => {
  it("returns first target when no condition result", () => {
    const nextMap: CompiledGraph["nextMap"] = new Map([["n1", [{ target: "n2" }, { target: "n3" }]]]);
    expect(nextNodeId("n1", nextMap)).toBe("n2");
  });

  it("returns target with on=true when conditionResult is true", () => {
    const nextMap: CompiledGraph["nextMap"] = new Map([
      [
        "c1",
        [
          { target: "a", on: "true" },
          { target: "b", on: "false" },
        ],
      ],
    ]);
    expect(nextNodeId("c1", nextMap, true)).toBe("a");
  });

  it("returns target with on=false when conditionResult is false", () => {
    const nextMap: CompiledGraph["nextMap"] = new Map([
      [
        "c1",
        [
          { target: "a", on: "true" },
          { target: "b", on: "false" },
        ],
      ],
    ]);
    expect(nextNodeId("c1", nextMap, false)).toBe("b");
  });

  it("returns null when no outgoing edges", () => {
    const nextMap = new Map<string, { target: string; on?: string }[]>();
    expect(nextNodeId("n1", nextMap)).toBe(null);
  });
});

describe("WorkflowRunError", () => {
  it("has code and optional nodeId", () => {
    const err = new WorkflowRunError("test", "UNKNOWN_NODE_TYPE", "node-1");
    expect(err.code).toBe("UNKNOWN_NODE_TYPE");
    expect(err.nodeId).toBe("node-1");
    expect(err.name).toBe("WorkflowRunError");
  });
});
