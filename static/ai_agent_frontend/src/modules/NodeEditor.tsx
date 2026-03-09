import React, { useCallback } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  useEdgesState,
  useNodesState,
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

  const onConnect = useCallback(
    (connection: any) => setEdges((eds) => [...eds, { ...connection, id: `${Date.now()}` }]),
    [setEdges],
  );

  return (
    <ReactFlow
      fitView
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
    >
      <Background />
      <MiniMap />
      <Controls position="top-left" />
    </ReactFlow>
  );
};

