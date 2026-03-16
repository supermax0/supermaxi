import { query, withTransaction } from "../../lib/db.js";
import type { PoolClient } from "pg";
import { evaluateSimpleCondition } from "./expression.js";
import { generateText } from "../ai/openai.service.js";
import { isRunnerImplemented } from "./node-registry.js";
import {
  EXTRACTOR_AGENT_PROMPT,
  FALLBACK_SAFETY_PROMPT,
  KNOWLEDGE_RAG_PROMPT,
  ROUTER_AGENT_PROMPT,
  SALES_AGENT_PROMPT,
} from "../../prompts/agent-templates.js";

const MAX_STEPS = 500;
const MAX_DURATION_MS = 60_000;

export type NodeDef = {
  id: string;
  type: string;
  data?: Record<string, unknown>;
};

export type EdgeDef = {
  source: string;
  target: string;
  on?: string;
};

type WorkflowGraph = {
  nodes: NodeDef[];
  edges: EdgeDef[];
};

/** Deterministic adjacency: for each source, list of { target, on? } in stable order. */
export type CompiledNext = { target: string; on?: string }[];

export type CompiledGraph = {
  entryNodeId: string;
  nodeMap: Map<string, NodeDef>;
  nextMap: Map<string, CompiledNext>;
};

export type WorkflowRunResult = {
  executionId: number;
  status: "success" | "failed";
  context: Record<string, unknown>;
};

export class WorkflowRunError extends Error {
  constructor(
    message: string,
    public readonly code: string,
    public readonly nodeId?: string,
  ) {
    super(message);
    this.name = "WorkflowRunError";
  }
}

function renderTemplate(input: string, context: Record<string, unknown>): string {
  return input.replace(/\{\{\s*([a-zA-Z0-9_.$-]+)\s*\}\}/g, (_, key: string) => {
    const value = context[key];
    return value === null || value === undefined ? "" : String(value);
  });
}

/**
 * Build deterministic execution plan from graph. Throws if no start node.
 */
export function compileGraph(graph: WorkflowGraph): CompiledGraph {
  const nodes = Array.isArray(graph?.nodes) ? (graph.nodes as NodeDef[]) : [];
  const edges = Array.isArray(graph?.edges) ? (graph.edges as EdgeDef[]) : [];

  const nodeMap = new Map<string, NodeDef>(nodes.map((n) => [n.id, n]));
  const nextMap = new Map<string, CompiledNext>();

  for (const e of edges) {
    const src = e.source;
    const tgt = e.target;
    if (!nodeMap.has(src) || !nodeMap.has(tgt)) continue;
    const list = nextMap.get(src) ?? [];
    list.push({ target: tgt, on: e.on });
    nextMap.set(src, list);
  }

  const startNode = nodes.find((n) => n.type === "start");
  const entryNodeId = startNode?.id ?? nodes[0]?.id;
  if (!entryNodeId || !nodeMap.has(entryNodeId)) {
    throw new WorkflowRunError("Workflow has no start node", "NO_START_NODE");
  }

  return { entryNodeId, nodeMap, nextMap };
}

export function nextNodeId(currentNodeId: string, nextMap: Map<string, CompiledNext>, conditionResult?: boolean): string | null {
  const candidates = nextMap.get(currentNodeId);
  if (!candidates?.length) return null;

  if (conditionResult === true) {
    const onTrue = candidates.find((c) => c.on === "true");
    return onTrue?.target ?? candidates[0].target;
  }
  if (conditionResult === false) {
    const onFalse = candidates.find((c) => c.on === "false");
    return onFalse?.target ?? candidates[0].target;
  }
  return candidates[0].target;
}

async function logNode(
  executionId: number,
  node: NodeDef,
  status: "running" | "success" | "failed",
  inputSnapshot?: Record<string, unknown>,
  outputSnapshot?: Record<string, unknown>,
  errorMessage?: string,
) {
  await query(
    `
      INSERT INTO ai_agent_execution_logs
      (execution_id, node_id, node_type, status, input_snapshot, output_snapshot, error_message)
      VALUES ($1, $2, $3, $4, $5, $6, $7)
    `,
    [
      executionId,
      node.id,
      node.type,
      status,
      inputSnapshot ? JSON.stringify(inputSnapshot) : null,
      outputSnapshot ? JSON.stringify(outputSnapshot) : null,
      errorMessage ?? null,
    ],
  );
}

async function runAiTemplateNode(
  prompt: string,
  context: Record<string, unknown>,
  maxTokens = 600,
): Promise<Record<string, unknown>> {
  const userMessage = renderTemplate(prompt, context);
  const output = await generateText(
    [
      { role: "system", content: "Return concise, production-safe output." },
      { role: "user", content: userMessage },
    ],
    maxTokens,
  );
  return { ai_output: output };
}

/** Node output contract for sql_save_order: order_id, customer_id, product_id, total_price. */
export type SqlSaveOrderOutput = {
  order_id: number;
  customer_id: number;
  product_id: number;
  total_price: number;
};

async function runSqlSaveOrder(
  client: PoolClient,
  context: Record<string, unknown>,
  nodeData?: Record<string, unknown>,
): Promise<SqlSaveOrderOutput> {
  const name = String(context.name ?? "عميل");
  const phone = String(context.phone ?? "").trim();
  const address = String(context.address ?? "");
  const productName = String(context.product_name ?? context.product ?? "منتج");
  const quantity = Number(context.quantity ?? 1) || 1;
  const price = Number(context.price ?? 0);
  const channelDefault = nodeData && typeof nodeData.channel_default === "string" ? nodeData.channel_default.trim() : "";
  const channel = String((context.channel ?? channelDefault) || "unknown");

  const customer = await client.query<{ id: number }>(
    `
      INSERT INTO customers (name, phone, address)
      VALUES ($1, $2, $3)
      ON CONFLICT (phone) DO UPDATE SET
        name = EXCLUDED.name,
        address = EXCLUDED.address
      RETURNING id
    `,
    [name, phone || `temp-${Date.now()}`, address],
  );

  const customerId = customer.rows[0].id;
  const product = await client.query<{ id: number }>(
    `
      INSERT INTO products (name, sku, price, stock)
      VALUES ($1, $2, $3, 0)
      ON CONFLICT (sku) DO UPDATE SET name = EXCLUDED.name
      RETURNING id
    `,
    [productName, `sku-${productName.toLowerCase().replace(/\s+/g, "-")}`, price],
  );

  const productId = product.rows[0].id;
  const totalPrice = Number((price * quantity).toFixed(2));
  const order = await client.query<{ id: number }>(
    `
      INSERT INTO orders (customer_id, product_id, quantity, total_price, status, channel)
      VALUES ($1, $2, $3, $4, 'pending', $5)
      RETURNING id
    `,
    [customerId, productId, quantity, totalPrice, channel],
  );

  return {
    order_id: order.rows[0].id,
    customer_id: customerId,
    product_id: productId,
    total_price: totalPrice,
  };
}

export type RunWorkflowOptions = {
  /** When provided, use this execution row and set status to running (queued -> running lifecycle). */
  executionId?: number;
};

export async function runWorkflowById(
  workflowId: number,
  tenantSlug: string,
  userId: string,
  initialContext: Record<string, unknown> = {},
  options: RunWorkflowOptions = {},
): Promise<WorkflowRunResult> {
  const workflowResult = await query<{ graph_json: WorkflowGraph }>(
    `
      SELECT w.graph_json
      FROM ai_agent_workflows w
      INNER JOIN ai_agents a ON a.id = w.agent_id
      WHERE w.id = $1 AND a.tenant_slug = $2 AND (a.user_id = $3 OR a.user_id IS NULL)
      LIMIT 1
    `,
    [workflowId, tenantSlug, userId],
  );

  if (!workflowResult.rowCount) {
    throw new Error("Workflow not found");
  }

  const graph = workflowResult.rows[0].graph_json;
  const compiled = compileGraph(graph);

  let executionId: number;
  if (options.executionId != null) {
    const updated = await query<{ id: number }>(
      `UPDATE ai_agent_executions SET status = 'running' WHERE id = $1 AND workflow_id = $2 AND status = 'queued' RETURNING id`,
      [options.executionId, workflowId],
    );
    if (!updated.rowCount) {
      throw new Error("Execution not found or not queued");
    }
    executionId = updated.rows[0].id;
  } else {
    const execution = await query<{ id: number }>(
      `
        INSERT INTO ai_agent_executions (workflow_id, status)
        VALUES ($1, 'running')
        RETURNING id
      `,
      [workflowId],
    );
    executionId = execution.rows[0].id;
  }
  const context: Record<string, unknown> = { ...initialContext };
  let currentNode: NodeDef | undefined = compiled.nodeMap.get(compiled.entryNodeId) ?? undefined;
  let stepCount = 0;
  const startTime = Date.now();

  try {
    while (currentNode) {
      if (stepCount >= MAX_STEPS) {
        throw new WorkflowRunError(`Execution exceeded max steps (${MAX_STEPS})`, "MAX_STEPS_EXCEEDED");
      }
      if (Date.now() - startTime > MAX_DURATION_MS) {
        throw new WorkflowRunError(`Execution exceeded max duration (${MAX_DURATION_MS}ms)`, "MAX_DURATION_EXCEEDED");
      }
      stepCount += 1;

      if (!isRunnerImplemented(currentNode.type)) {
        throw new WorkflowRunError(
          `Unknown or unsupported node type: ${currentNode.type}`,
          "UNKNOWN_NODE_TYPE",
          currentNode.id,
        );
      }

      await logNode(executionId, currentNode, "running", context);
      const data = currentNode.data ?? {};
      let output: Record<string, unknown> = {};
      let conditionResult: boolean | undefined;

      switch (currentNode.type) {
        case "start":
          output = { started: true };
          break;
        case "router_agent":
          output = await runAiTemplateNode(ROUTER_AGENT_PROMPT + "\n\nMessage: {{message_text}}", context, 350);
          break;
        case "ai_extractor":
          output = await runAiTemplateNode(EXTRACTOR_AGENT_PROMPT + "\n\nMessage: {{message_text}}", context, 400);
          break;
        case "knowledge_agent":
          output = await runAiTemplateNode(KNOWLEDGE_RAG_PROMPT + "\n\nMessage: {{message_text}}", context, 450);
          break;
        case "sales_agent":
          output = await runAiTemplateNode(SALES_AGENT_PROMPT + "\n\nMessage: {{message_text}}", context, 450);
          break;
        case "fallback_safety":
          output = await runAiTemplateNode(FALLBACK_SAFETY_PROMPT + "\n\nMessage: {{message_text}}", context, 200);
          break;
        case "condition":
          conditionResult = evaluateSimpleCondition(String(data.expr ?? ""), context);
          output = { condition_result: conditionResult };
          context.condition_result = conditionResult;
          break;
        case "sql_save_order":
          output = await withTransaction((client) => runSqlSaveOrder(client, context, data));
          break;
        case "telegram_reply":
          output = {
            reply_text: renderTemplate(String(data.template ?? "{{ai_output}}"), context),
          };
          context.reply_text = output.reply_text as string;
          break;
        case "end":
          output = { ended: true };
          break;
        default:
          throw new WorkflowRunError(`Unsupported node type: ${currentNode.type}`, "UNKNOWN_NODE_TYPE", currentNode.id);
      }

      Object.assign(context, output);
      await logNode(executionId, currentNode, "success", context, output);

      const nextId = nextNodeId(currentNode.id, compiled.nextMap, conditionResult);
      currentNode = nextId ? compiled.nodeMap.get(nextId) : undefined;
    }

    await query(
      `
        UPDATE ai_agent_executions
        SET status = 'success', finished_at = NOW(), result_summary = $2
        WHERE id = $1
      `,
      [executionId, JSON.stringify({ keys: Object.keys(context) })],
    );
    return { executionId, status: "success", context };
  } catch (error) {
    const isWorkflowError = error instanceof WorkflowRunError;
    const code = isWorkflowError ? error.code : "WORKFLOW_ERROR";
    const message = error instanceof Error ? error.message : "Unknown workflow error";
    const nodeId = isWorkflowError ? error.nodeId : undefined;

    await query(
      `
        UPDATE ai_agent_executions
        SET status = 'failed', finished_at = NOW(), error_message = $2
        WHERE id = $1
      `,
      [executionId, message],
    );
    if (currentNode) {
      await logNode(executionId, currentNode, "failed", context, undefined, `${code}: ${message}`);
    }
    return { executionId, status: "failed", context: { ...context, error: message, error_code: code, node_id: nodeId } };
  }
}
