import { create } from "zustand";
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  Connection,
  Edge,
  EdgeChange,
  Node,
  NodeChange,
} from "reactflow";

export type WorkflowMeta = {
  id?: number;
  agentId?: number;
  name: string;
  description?: string;
  isActive: boolean;
};

type EditorStore = {
  meta: WorkflowMeta;
  nodes: Node[];
  edges: Edge[];
  selectedNodeId?: string;
  /** عقدة التنفيذ الحالي (للتمييز الأخضر في المحرر أثناء تشغيل الوورك فلو). */
  activeExecutionNodeId?: string;
  setMeta: (partial: Partial<WorkflowMeta>) => void;
  setActiveExecutionNodeId: (id?: string) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  addConnection: (connection: Connection) => void;
  addNode: (node: Node) => void;
  removeNode: (id: string) => void;
  removeEdge: (id: string) => void;
  setSelectedNodeId: (id?: string) => void;
  updateNodeData: (id: string, data: Record<string, unknown>) => void;
  loadFromGraph: (payload: {
    nodes: Node[];
    edges?: Edge[];
    meta?: Partial<WorkflowMeta>;
    id?: number;
    agentId?: number;
  }) => void;
  getGraphPayload: () => { meta: WorkflowMeta; nodes: Node[]; edges: Edge[] };
  reset: () => void;
};

const initialMeta: WorkflowMeta = {
  name: "وورك فلو جديد",
  description: "",
  isActive: true,
};

const initialNodes: Node[] = [
  {
    id: "start-1",
    type: "start",
    position: { x: 0, y: 0 },
    data: { label: "Start" },
  },
];

export const useEditorStore = create<EditorStore>((set, get) => ({
  meta: initialMeta,
  nodes: initialNodes,
  edges: [],
  selectedNodeId: undefined,
  activeExecutionNodeId: undefined,

  setMeta: (partial) => set((state) => ({ meta: { ...state.meta, ...partial } })),
  setActiveExecutionNodeId: (id) => set({ activeExecutionNodeId: id }),

  onNodesChange: (changes) =>
    set((state) => ({
      nodes: applyNodeChanges(changes, state.nodes),
    })),

  onEdgesChange: (changes) =>
    set((state) => ({
      edges: applyEdgeChanges(changes, state.edges),
    })),

  addConnection: (connection) =>
    set((state) => ({
      edges: addEdge({ ...connection, id: `${Date.now()}` }, state.edges),
    })),

  addNode: (node) =>
    set((state) => ({
      nodes: state.nodes.concat(node),
    })),

  removeNode: (id) =>
    set((state) => ({
      nodes: state.nodes.filter((n) => n.id !== id),
      edges: state.edges.filter((e) => e.source !== id && e.target !== id),
      selectedNodeId: state.selectedNodeId === id ? undefined : state.selectedNodeId,
      activeExecutionNodeId: state.activeExecutionNodeId === id ? undefined : state.activeExecutionNodeId,
    })),

  removeEdge: (id) =>
    set((state) => ({
      edges: state.edges.filter((e) => e.id !== id),
    })),

  setSelectedNodeId: (id) => set({ selectedNodeId: id }),

  updateNodeData: (id, data) =>
    set((state) => ({
      nodes: state.nodes.map((node) =>
        node.id === id ? { ...node, data: { ...(node.data || {}), ...data } } : node,
      ),
    })),

  loadFromGraph: ({ nodes, edges = [], meta, id, agentId }) =>
    set(() => ({
      meta: { ...initialMeta, ...meta, id, agentId },
      nodes: nodes.length ? nodes : initialNodes,
      edges,
      selectedNodeId: undefined,
      activeExecutionNodeId: undefined,
    })),

  getGraphPayload: () => {
    const { meta, nodes, edges } = get();
    return { meta, nodes, edges };
  },

  reset: () =>
    set(() => ({
      meta: initialMeta,
      nodes: initialNodes,
      edges: [],
      selectedNodeId: undefined,
      activeExecutionNodeId: undefined,
    })),
}));

