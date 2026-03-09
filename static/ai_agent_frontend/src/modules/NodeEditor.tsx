import React, { useCallback, useRef } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "reactflow";
import "reactflow/dist/style.css";

const initialNodes: Node[] = [
  {
    id: "start-1",
    type: "default",
    position: { x: 0, y: 0 },
    data: { label: "Start" },
  },
];
const initialEdges: Edge[] = [];

export const NodeEditor: React.FC = () => {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const reactFlowWrapper = useRef<HTMLDivElement | null>(null);
  const { project } = useReactFlow();

  const onConnect = useCallback(
    (connection: any) => setEdges((eds) => [...eds, { ...connection, id: `${Date.now()}` }]),
    [setEdges],
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

      const newNode: Node = {
        id,
        type: "default",
        position,
        data: {
          label: labelMap[nodeType] || nodeType,
        },
      };

      setNodes((nds) => nds.concat(newNode));
    },
    [project, setNodes],
  );

  return (
    <div ref={reactFlowWrapper} className="h-full w-full">
      <ReactFlow
        fitView
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onDrop={onDrop}
        onDragOver={onDragOver}
      >
        <Background />
        <MiniMap />
        <Controls position="top-left" />
      </ReactFlow>
    </div>
  );
};

