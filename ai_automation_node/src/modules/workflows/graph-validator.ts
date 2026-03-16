/**
 * Semantic graph validation for workflow create/update.
 * Returns structured errors (code, node_id, field, message) for API responses.
 */

import { isAllowedNodeType } from "./node-registry.js";

export interface GraphNode {
  id: string;
  type?: string;
  data?: Record<string, unknown>;
  position?: { x: number; y: number };
}

export interface GraphEdge {
  id?: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
  on?: string;
}

export interface ValidationError {
  code: string;
  node_id?: string;
  edge_id?: string;
  field?: string;
  message: string;
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationError[];
}

function err(
  code: string,
  message: string,
  opts?: { node_id?: string; edge_id?: string; field?: string },
): ValidationError {
  return { code, message, ...opts };
}

/**
 * Validates workflow graph semantics. Call before persisting on create/update.
 */
export function validateGraph(nodes: GraphNode[], edges: GraphEdge[]): ValidationResult {
  const errors: ValidationError[] = [];

  const nodeIds = new Set<string>();
  for (const n of nodes) {
    const id = n?.id;
    if (typeof id !== "string" || !id.trim()) {
      errors.push(err("invalid_node", "Node missing or invalid id", { node_id: id as string }));
      continue;
    }
    if (nodeIds.has(id)) {
      errors.push(err("duplicate_node_id", `Duplicate node id: ${id}`, { node_id: id }));
    }
    nodeIds.add(id);

    const type = (n?.type ?? "").toString().trim();
    if (!type) {
      errors.push(err("missing_node_type", "Node must have a type", { node_id: id }));
    } else if (!isAllowedNodeType(type)) {
      errors.push(err("unknown_node_type", `Unknown node type: ${type}`, { node_id: id, field: "type" }));
    }
  }

  const startNodes = nodes.filter((n) => n?.type === "start");
  if (startNodes.length === 0) {
    errors.push(err("missing_start", "Graph must have exactly one Start node"));
  } else if (startNodes.length > 1) {
    errors.push(
      err("multiple_start", "Graph must have only one Start node", {
        node_id: startNodes.map((n) => n.id).join(","),
      }),
    );
  }

  for (const e of edges) {
    const src = e?.source;
    const tgt = e?.target;
    if (typeof src !== "string" || !src.trim()) {
      errors.push(err("invalid_edge_source", "Edge has missing or invalid source", { edge_id: e?.id as string }));
      continue;
    }
    if (typeof tgt !== "string" || !tgt.trim()) {
      errors.push(err("invalid_edge_target", "Edge has missing or invalid target", { edge_id: e?.id as string }));
      continue;
    }
    if (!nodeIds.has(src)) {
      errors.push(err("edge_source_not_found", `Edge source node not found: ${src}`, { node_id: src, edge_id: e?.id as string }));
    }
    if (!nodeIds.has(tgt)) {
      errors.push(err("edge_target_not_found", `Edge target node not found: ${tgt}`, { node_id: tgt, edge_id: e?.id as string }));
    }
    const onVal = e?.on;
    if (onVal !== undefined && onVal !== null && onVal !== "true" && onVal !== "false") {
      errors.push(
        err("invalid_branch_label", "Condition branch edge 'on' must be 'true' or 'false'", {
          edge_id: (e as { id?: string }).id,
          field: "on",
        }),
      );
    }
  }

  const reachable = new Set<string>();
  const startId = startNodes[0]?.id;
  if (startId && nodeIds.has(startId)) {
    const outbound = new Map<string, string[]>();
    for (const e of edges) {
      if (!nodeIds.has(e.source) || !nodeIds.has(e.target)) continue;
      const list = outbound.get(e.source) ?? [];
      if (!list.includes(e.target)) list.push(e.target);
      outbound.set(e.source, list);
    }
    const queue = [startId];
    reachable.add(startId);
    while (queue.length) {
      const cur = queue.shift()!;
      for (const next of outbound.get(cur) ?? []) {
        if (!reachable.has(next)) {
          reachable.add(next);
          queue.push(next);
        }
      }
    }
  }

  for (const n of nodes) {
    const id = n?.id;
    if (id && !reachable.has(id) && n?.type !== "start") {
      errors.push(err("unreachable_node", `Node is not reachable from Start: ${id}`, { node_id: id }));
    }
  }

  return {
    valid: errors.length === 0,
    errors,
  };
}
