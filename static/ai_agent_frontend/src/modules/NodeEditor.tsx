import React, { useCallback, useRef } from "react";
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

export const NodeEditor: React.FC = () => {
  const nodes = useEditorStore((s) => s.nodes);
  const edges = useEditorStore((s) => s.edges);
  const onNodesChange = useEditorStore((s) => s.onNodesChange);
  const onEdgesChange = useEditorStore((s) => s.onEdgesChange);
  const addConnection = useEditorStore((s) => s.addConnection);
  const addNode = useEditorStore((s) => s.addNode);
  const setSelectedNodeId = useEditorStore((s) => s.setSelectedNodeId);
  const reactFlowWrapper = useRef<HTMLDivElement | null>(null);
  const { project } = useReactFlow();

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
        end: "End",
      };

      const newNode = {
        id,
        type: nodeType,
        position,
        data: {
          label: labelMap[nodeType] || nodeType,
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
  }, [setSelectedNodeId]);

  return (
    <div ref={reactFlowWrapper} className="relative h-full w-full">
      <ReactFlow
        fitView
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
      >
        <Background />
        <MiniMap />
        <Controls position="top-left" />
        {nodes.length === 0 && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-slate-500">
            اسحب عقدة Start من القائمة لبدء إنشاء الوورك فلو.
          </div>
        )}
      </ReactFlow>
    </div>
  );
};

