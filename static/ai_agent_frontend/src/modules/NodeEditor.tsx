import React, { useCallback, useRef, useState, useEffect } from "react";
import { createPortal } from "react-dom";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Connection,
  useReactFlow,
} from "reactflow";
import "reactflow/dist/style.css";
import { nodeTypes } from "./NodeTypes";
import { useEditorStore } from "./store";

type ContextMenuTarget = { type: "node"; id: string } | { type: "edge"; id: string } | { type: "pane" };

export const NodeEditor: React.FC = () => {
  const nodes = useEditorStore((s) => s.nodes);
  const edges = useEditorStore((s) => s.edges);
  const onNodesChange = useEditorStore((s) => s.onNodesChange);
  const onEdgesChange = useEditorStore((s) => s.onEdgesChange);
  const addConnection = useEditorStore((s) => s.addConnection);
  const addNode = useEditorStore((s) => s.addNode);
  const removeNode = useEditorStore((s) => s.removeNode);
  const removeEdge = useEditorStore((s) => s.removeEdge);
  const setSelectedNodeId = useEditorStore((s) => s.setSelectedNodeId);
  const reactFlowWrapper = useRef<HTMLDivElement | null>(null);
  const fitViewRef = useRef<((opts?: { padding?: number; duration?: number }) => void) | null>(null);
  const { project } = useReactFlow();

  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; target: ContextMenuTarget } | null>(null);

  const runFitView = useCallback(() => {
    fitViewRef.current?.({ padding: 0.15, duration: 200 });
  }, []);

  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    window.addEventListener("click", close);
    window.addEventListener("contextmenu", close);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("contextmenu", close);
    };
  }, [contextMenu]);

  useEffect(() => {
    const el = reactFlowWrapper.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      runFitView();
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [runFitView]);

  useEffect(() => {
    const t = setTimeout(runFitView, 100);
    return () => clearTimeout(t);
  }, [runFitView]);

  const onConnect = useCallback(
    (connection: Connection) => {
      addConnection(connection);
    },
    [addConnection],
  );

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const nodeType = event.dataTransfer.getData("application/reactflow");
      if (!nodeType || !reactFlowWrapper.current) return;

      const bounds = reactFlowWrapper.current.getBoundingClientRect();
      const position = project({
        x: event.clientX - bounds.left,
        y: event.clientY - bounds.top,
      });

      const id = `${nodeType}-${Date.now()}`;
      const labelMap: Record<string, string> = {
        start: "Start",
        ai: "AI Agent",
        image: "Image Generator",
        caption: "Caption Generator",
        publisher: "Publisher",
        scheduler: "Scheduler",
        "comment-listener": "Comment Listener",
        "auto-reply": "Auto Reply",
        sql_save_order: "SQL حفظ الطلب",
        conversation_context: "محادثة (سياق)",
        end: "End",
      };

      const newNode = {
        id,
        type: nodeType,
        position,
        data: {
          label: labelMap[nodeType] || nodeType,
          ...(nodeType === "conversation_context"
            ? { max_chars: 6000, include_current_message: true, include_last_reply: true }
            : {}),
        },
      };

      addNode(newNode);
    },
    [project, addNode],
  );

  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: any) => {
      setSelectedNodeId(node.id);
    },
    [setSelectedNodeId],
  );

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(undefined);
    setContextMenu(null);
  }, [setSelectedNodeId]);

  const onNodeContextMenu = useCallback((e: React.MouseEvent, node: { id: string }) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ x: e.clientX, y: e.clientY, target: { type: "node", id: node.id } });
  }, []);

  const onEdgeContextMenu = useCallback((e: React.MouseEvent, edge: { id: string }) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ x: e.clientX, y: e.clientY, target: { type: "edge", id: edge.id } });
  }, []);

  const onPaneContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, target: { type: "pane" } });
  }, []);

  const handleContextAction = useCallback(
    (action: "deleteNode" | "deleteEdge") => {
      if (!contextMenu) return;
      if (action === "deleteNode" && contextMenu.target.type === "node") {
        removeNode(contextMenu.target.id);
      }
      if (action === "deleteEdge" && contextMenu.target.type === "edge") {
        removeEdge(contextMenu.target.id);
      }
      setContextMenu(null);
    },
    [contextMenu, removeNode, removeEdge],
  );

  return (
    <div
      ref={reactFlowWrapper}
      className="relative h-full w-full"
      onContextMenu={(e) => e.preventDefault()}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onInit={(state) => {
          fitViewRef.current = () => state.fitView({ padding: 0.15, duration: 200 });
          state.fitView({ padding: 0.15, duration: 200 });
        }}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        onNodeContextMenu={onNodeContextMenu}
        onEdgeContextMenu={onEdgeContextMenu}
        onPaneContextMenu={onPaneContextMenu}
        nodeTypes={nodeTypes}
        defaultEdgeOptions={{ type: "smoothstep", style: { stroke: "#38bdf8" }, animated: true }}
      >
        <Background color="#1e293b" gap={16} />
        <MiniMap />
        <Controls position="top-left" />
        {nodes.length === 0 && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-slate-500">
            اسحب عقدة Start من القائمة لبدء إنشاء الوورك فلو.
          </div>
        )}
      </ReactFlow>

      {contextMenu &&
        createPortal(
          <div
            className="fixed z-[10000] min-w-[160px] rounded-workflow border border-[#334155] bg-[#111827] py-1 shadow-card"
            style={{ left: contextMenu.x, top: contextMenu.y }}
            onClick={(e) => e.stopPropagation()}
            onContextMenu={(e) => e.preventDefault()}
          >
            {contextMenu.target.type === "node" && (
              <button
                type="button"
                className="w-full px-3 py-2 text-right text-sm text-slate-200 hover:bg-slate-800 hover:text-rose-400"
                onClick={() => handleContextAction("deleteNode")}
              >
                حذف العقدة
              </button>
            )}
            {contextMenu.target.type === "edge" && (
              <button
                type="button"
                className="w-full px-3 py-2 text-right text-sm text-slate-200 hover:bg-slate-800 hover:text-amber-400"
                onClick={() => handleContextAction("deleteEdge")}
              >
                فك الربط
              </button>
            )}
            {contextMenu.target.type === "pane" && (
              <div className="px-3 py-2 text-right text-xs text-slate-500">
                اسحب عقدة من القائمة أو انقر يميناً على عقدة/رابط
              </div>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
};

