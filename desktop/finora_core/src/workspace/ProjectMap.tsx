import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  useNodesState,
  useNodesInitialized,
  useReactFlow,
  type Node,
  type NodeProps,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Database, GitBranch, LayoutPanelTop, Network, Plug, ShieldCheck, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useCan } from "../data/can";
import { useSource } from "../data/hooks";
import { FinoraButton, errorText } from "../ui/primitives";
import { toast } from "../ui/toast";
import {
  KIND_COLORS,
  KIND_LABELS,
  downloadGraph,
  relatedNodes,
  type GraphNode,
  type ProjectConnection,
  type ProjectGraph,
} from "./projectGraph";

type MapNode = Node<GraphNode, "project">;
const ICONS = {
  page: LayoutPanelTop,
  feature: Sparkles,
  entity: Database,
  integration: Plug,
  role: ShieldCheck,
  workflow: GitBranch,
  step: GitBranch,
};

function MapCard({ data, selected }: NodeProps<MapNode>) {
  const Icon = ICONS[data.kind];
  return (
    <div
      className={`pm-node ${selected ? "is-selected" : ""}`}
      style={{ "--node-color": KIND_COLORS[data.kind] } as React.CSSProperties}
      dir="rtl"
    >
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <span className="pm-node-kind">
        <Icon size={14} />
        {KIND_LABELS[data.kind]}
      </span>
      <strong>{data.title}</strong>
      <small>
        {data.kind === "step"
          ? String(data.details.role ?? "")
          : data.kind === "page"
            ? data.details.phase === "later"
              ? "مرحلة لاحقة"
              : "نسخة أولية"
            : data.description.slice(0, 66)}
      </small>
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  );
}
const NODE_TYPES = { project: MapCard };
function AutoFit({ layoutKey }: { layoutKey: string }) {
  const initialized = useNodesInitialized();
  const { fitView } = useReactFlow();
  useEffect(() => {
    if (!initialized) return;
    let second = 0;
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(
        () => void fitView({ padding: 0.18, minZoom: 0.08, maxZoom: 1, duration: 180 }),
      );
    });
    return () => {
      cancelAnimationFrame(first);
      cancelAnimationFrame(second);
    };
  }, [initialized, layoutKey, fitView]);
  return null;
}
const DETAIL_LABELS: Record<string, string> = {
  features: "ميزات الصفحة",
  roles: "من يستخدمها",
  acceptance: "معايير القبول",
  pageAcceptance: "معايير قبول صفحتها",
  fields: "حقول البيانات",
  relatedTo: "بيانات مرتبطة",
  permissions: "الصلاحيات",
  requiresClientAccess: "يحتاج صلاحيات العميل",
  terminal: "نهاية المسار",
  sequence: "ترتيب الخطوة",
  page: "الصفحة",
  role: "الدور",
};

function Details({
  node,
  edge,
  graph,
  onSelect,
}: {
  node?: GraphNode;
  edge?: ProjectGraph["edges"][number];
  graph: ProjectGraph;
  onSelect: (id: string) => void;
}) {
  const connections = node ? graph.edges.filter((e) => e.source === node.id || e.target === node.id) : [];
  return (
    <aside className="pm-details" aria-label="تفاصيل العنصر" dir="rtl">
      {node ? (
        <>
          <span className="pm-kicker">{KIND_LABELS[node.kind]}</span>
          <h3>{node.title}</h3>
          <p>{node.description}</p>
          {Object.entries(node.details)
            .filter(([key]) => DETAIL_LABELS[key])
            .map(([key, value]) => (
              <section key={key}>
                <h4>{DETAIL_LABELS[key]}</h4>
                {Array.isArray(value) ? (
                  <ul>
                    {value.map((v, i) => (
                      <li key={i}>{String(v)}</li>
                    ))}
                  </ul>
                ) : (
                  <p>{typeof value === "boolean" ? (value ? "نعم" : "لا") : String(value)}</p>
                )}
              </section>
            ))}
          {graph.unresolvedFeatures.includes(node.id) && (
            <p className="pm-unresolved">هذه الميزة تحتاج توضيح ارتباطها قبل اعتماد اقتراحات الترابط.</p>
          )}
          <h4>الارتباطات والتأثير · {connections.length}</h4>
          {connections.map((e) => {
            const other = graph.nodes.find((n) => n.id === (e.source === node.id ? e.target : e.source));
            return (
              <button key={e.id} className="pm-related" onClick={() => other && onSelect(other.id)}>
                <span>
                  {e.source === node.id ? "يؤثر / يرتبط بـ" : "مرتبط من"} ·{" "}
                  {e.basis === "proposed"
                    ? "اقتراح"
                    : e.basis === "text_reference"
                      ? "ذكر في الوصف"
                      : "من الخطة"}
                </span>
                <strong>{other?.title}</strong>
                <small>{e.label}</small>
              </button>
            );
          })}
        </>
      ) : edge ? (
        <>
          <span className="pm-kicker">تفاصيل الارتباط</span>
          <h3>{edge.label}</h3>
          <p>
            {edge.basis === "proposed"
              ? "اقتراح من تحليل الذكاء؛ يبقى منفصلاً عن النطاق المعتمد."
              : edge.basis === "text_reference"
                ? "مرجع مستنتج من ذكر البيانات في وصف الميزة."
                : "ارتباط موجود في مواصفات المشروع."}
          </p>
          {[edge.source, edge.target].map((id) => (
            <button key={id} className="pm-related" onClick={() => onSelect(id)}>
              {graph.nodes.find((n) => n.id === id)?.title}
            </button>
          ))}
        </>
      ) : (
        <>
          <Network size={28} />
          <h3>كل جزء إله مكان واضح</h3>
          <p>
            اضغط على صفحة أو ميزة حتى تشوف شرحها، صلاحياتها، وما ترتبط به. وتگدر تضغط على خط الربط لشرح
            العلاقة.
          </p>
          <p>اسحب لترتيب العناصر، أو حرّك مساحة المخطط للتنقل. استخدم التكبير حتى تشوف التفاصيل.</p>
        </>
      )}
    </aside>
  );
}

function ConnectionPanel({ conversationId, onClose }: { conversationId: string; onClose: () => void }) {
  const src = useSource();
  const [connection, setConnection] = useState<ProjectConnection | null>(null);
  const [format, setFormat] = useState("json");
  const create = useMutation({
    mutationFn: async () => {
      if (!src.createProjectConnection) throw new Error("اتصال MCP غير متاح بهذا المصدر");
      setConnection(await src.createProjectConnection(conversationId));
    },
    onError: (e) => toast.error(errorText(e)),
  });
  const revoke = useMutation({
    mutationFn: async () => {
      if (!src.revokeProjectConnection) throw new Error("إلغاء الاتصال غير متاح بهذا المصدر");
      await src.revokeProjectConnection(conversationId);
      setConnection(null);
    },
    onSuccess: () => toast.success("تم إلغاء اتصال هذه الخطة"),
    onError: (e) => toast.error(errorText(e)),
  });
  const config = connection
    ? format === "json"
      ? JSON.stringify(
          {
            mcpServers: {
              finoraProject: {
                type: "http",
                url: connection.endpoint ?? connection.endpointPath,
                headers: { Authorization: `Bearer ${connection.token}` },
              },
            },
          },
          null,
          2,
        )
      : `[mcp_servers.finora_project]\nurl = ${JSON.stringify(connection.endpoint ?? connection.endpointPath)}\n\n[mcp_servers.finora_project.http_headers]\nAuthorization = ${JSON.stringify(`Bearer ${connection.token}`)}`
    : "";
  return (
    <section className="pm-connection" aria-label="ربط خطة العميل" dir="rtl">
      <header>
        <h3>
          <Plug size={18} /> ربط MCP
        </h3>
        <button onClick={onClose} aria-label="إغلاق إعداد الربط">
          <X size={18} />
        </button>
      </header>
      <p>
        اربط أداة البرمجة بالخطة والمخطط وتفاصيل كل عنصر. الاتصال يقرأ مشروع هذا العميل، وصلاحيات التنفيذ
        والاعتماد تبقى داخل فينورا.
      </p>
      {!connection ? (
        <FinoraButton size="sm" loading={create.isPending} onClick={() => create.mutate()}>
          إنشاء اتصال قراءة · 7 أيام
        </FinoraButton>
      ) : (
        <>
          <label>
            إعداد أداة الربط
            <select value={format} onChange={(e) => setFormat(e.target.value)}>
              <option value="json">JSON · أدوات MCP</option>
              <option value="codex">Codex · TOML</option>
            </select>
          </label>
          <textarea readOnly value={config} rows={9} aria-label="إعداد اتصال MCP" dir="ltr" />
          <p>
            ينتهي في {new Date(connection.expiresAt).toLocaleDateString("ar-IQ")}. إعداد الاتصال يظهر هنا مرة
            واحدة؛ انسخه لأداة الربط.
          </p>
          <FinoraButton
            size="sm"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(config);
                toast.success("نُسخ إعداد الربط");
              } catch {
                toast.error("تعذر النسخ؛ انسخ الإعداد من الحقل");
              }
            }}
          >
            نسخ إعداد الاتصال
          </FinoraButton>
        </>
      )}
      {src.revokeProjectConnection && (
        <FinoraButton size="sm" variant="ghost" loading={revoke.isPending} onClick={() => revoke.mutate()}>
          إلغاء اتصال هذه الخطة
        </FinoraButton>
      )}
    </section>
  );
}

function Board({ graph, conversationId }: { graph: ProjectGraph; conversationId: string }) {
  const src = useSource(),
    qc = useQueryClient();
  const [view, setView] = useState("pages"),
    [pageId, setPageId] = useState(graph.nodes.find((n) => n.kind === "page")?.id ?? "");
  const [flowId, setFlowId] = useState(graph.nodes.find((n) => n.kind === "workflow")?.id ?? ""),
    [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null),
    [selectedEdge, setSelectedEdge] = useState<string | null>(null),
    [connection, setConnection] = useState(false);
  const [exportFormat, setExportFormat] = useState<"json" | "n8n" | "svg">("json"),
    [exportScope, setExportScope] = useState("all");
  const analyze = useMutation({
    mutationFn: async () => {
      if (!src.analyzeProjectGraph) throw new Error("التحليل غير متاح بهذا المصدر");
      return src.analyzeProjectGraph(conversationId, graph.planHash);
    },
    onSuccess: (data) => {
      qc.setQueryData(["project-graph", conversationId], data);
      toast.success("تم تحليل الترابطات؛ الاقتراحات ظاهرة بخط متقطع");
    },
    onError: (e) => toast.error(errorText(e)),
  });
  const autoAnalysis = useRef(false);
  const { mutate: runAnalysis } = analyze;
  useEffect(() => {
    if (
      autoAnalysis.current ||
      graph.enriched ||
      !src.analyzeProjectGraph ||
      !graph.nodes.some((n) => n.kind === "feature")
    )
      return;
    autoAnalysis.current = true;
    runAnalysis();
  }, [graph.enriched, graph.nodes, src.analyzeProjectGraph, runAnalysis]);
  const visible = useMemo(() => {
    let ids = new Set(graph.nodes.map((n) => n.id));
    if (view === "pages") ids = new Set(graph.nodes.filter((n) => n.kind === "page").map((n) => n.id));
    if (view === "features") {
      const features = graph.nodes.filter((n) => n.parentId === pageId && n.kind === "feature");
      ids = new Set([pageId, ...features.flatMap((n) => [...relatedNodes(graph, n.id)])]);
    }
    if (view === "workflows")
      ids = new Set([flowId, ...graph.nodes.filter((n) => n.parentId === flowId).map((n) => n.id)]);
    if (search.trim())
      ids = new Set(
        graph.nodes
          .filter((n) => ids.has(n.id) && `${n.title} ${n.description}`.includes(search.trim()))
          .map((n) => n.id),
      );
    const subset = graph.nodes.filter((n) => ids.has(n.id));
    const counters: Record<string, number> = {};
    return subset.map((n, i): MapNode => {
      let x = 0,
        y = i * 140;
      if (view === "pages") {
        x = (i % 3) * 360;
        y = Math.floor(i / 3) * 180;
      } else if (view === "workflows") {
        x = n.kind === "workflow" ? 0 : 350;
        y = n.kind === "workflow" ? 0 : (i - 1) * 150;
      } else if (view === "features") {
        x = n.id === pageId ? 0 : n.kind === "feature" && n.parentId === pageId ? 360 : 760;
        const count = (counters[x] ?? 0) + 1;
        counters[x] = count;
        y = (count - 1) * 140;
      } else {
        x = n.position.x;
        y = n.position.y;
      }
      return { id: n.id, type: "project", data: n, position: { x, y } };
    });
  }, [graph, view, pageId, flowId, search]);
  const [nodes, setNodes, onNodesChange] = useNodesState<MapNode>(visible);
  useEffect(() => {
    setNodes(visible);
  }, [visible, setNodes]);
  const nodeIds = new Set(nodes.map((n) => n.id));
  const neighbors = selectedId ? relatedNodes(graph, selectedId) : null;
  const edges: Edge[] = graph.edges
    .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map((e) => ({
      ...e,
      label: view === "workflows" || e.id === selectedEdge ? e.label : undefined,
      type: "smoothstep",
      animated: e.id === selectedEdge,
      style: {
        stroke: e.id === selectedEdge ? "#5b63f0" : e.basis === "proposed" ? "#ba83a2" : "#b9bfdc",
        strokeWidth: selectedId && (e.source === selectedId || e.target === selectedId) ? 2.6 : 1.6,
        strokeDasharray: e.basis === "declared" ? undefined : "6 5",
        opacity: neighbors && !neighbors.has(e.source) && !neighbors.has(e.target) ? 0.2 : 1,
      },
      labelStyle: { fill: "#4f5372", fontSize: 11 },
      labelBgStyle: { fill: "#fff", fillOpacity: 0.96 },
      markerEnd: { type: "arrowclosed", color: e.basis === "proposed" ? "#ba83a2" : "#b9bfdc" },
    }));
  const select = (id: string) => {
    setSelectedId(id);
    setSelectedEdge(null);
    if (!nodeIds.has(id)) {
      setView("all");
      setSearch("");
    }
    setNodes((current) => current.map((n) => ({ ...n, selected: n.id === id })));
  };
  const selected = graph.nodes.find((n) => n.id === selectedId);
  const [exporting, setExporting] = useState(false);
  const exportMap = async () => {
    const positions = new Map(nodes.map((n) => [n.id, n.position]));
    const data = {
      ...graph,
      nodes: graph.nodes
        .filter((n) => exportScope === "all" || nodeIds.has(n.id))
        .map((n) => ({
          ...n,
          position:
            exportScope === "all" && view !== "all" ? n.position : (positions.get(n.id) ?? n.position),
        })),
      edges: graph.edges.filter(
        (e) => exportScope === "all" || (nodeIds.has(e.source) && nodeIds.has(e.target)),
      ),
      unresolvedFeatures: graph.unresolvedFeatures.filter((id) => exportScope === "all" || nodeIds.has(id)),
    };
    setExporting(true);
    try {
      if (await downloadGraph(data, exportFormat)) toast.success("تم تصدير المخطط");
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setExporting(false);
    }
  };
  return (
    <>
      <div className="pm-toolbar" dir="rtl">
        <nav aria-label="عرض المخطط">
          {(
            [
              ["pages", "الصفحات"],
              ["features", "الميزات وترابطها"],
              ["workflows", "مسارات العمل"],
              ["all", "كل الترابطات"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              aria-pressed={view === key}
              onClick={() => {
                setView(key);
                setSearch("");
                setSelectedId(null);
                setSelectedEdge(null);
              }}
            >
              {label}
            </button>
          ))}
        </nav>
        {view === "features" && (
          <select aria-label="صفحة الميزات" value={pageId} onChange={(e) => setPageId(e.target.value)}>
            {graph.nodes
              .filter((n) => n.kind === "page")
              .map((n) => (
                <option key={n.id} value={n.id}>
                  {n.title}
                </option>
              ))}
          </select>
        )}
        {view === "workflows" && (
          <select aria-label="مسار العمل" value={flowId} onChange={(e) => setFlowId(e.target.value)}>
            {graph.nodes
              .filter((n) => n.kind === "workflow")
              .map((n) => (
                <option key={n.id} value={n.id}>
                  {n.title}
                </option>
              ))}
          </select>
        )}
        <input
          aria-label="بحث بالمخطط"
          placeholder="ابحث عن صفحة أو ميزة…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {src.analyzeProjectGraph && (
          <FinoraButton
            size="sm"
            variant="ghost"
            loading={analyze.isPending}
            onClick={() => analyze.mutate()}
          >
            <Sparkles size={14} />
            {graph.enriched ? "تحديث تحليل الترابطات" : "تحليل الترابطات بالذكاء"}
          </FinoraButton>
        )}
      </div>
      <div className="pm-body">
        <div className="pm-canvas" dir="ltr">
          <ReactFlow
            key={`${view}-${pageId}-${flowId}`}
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            onNodesChange={onNodesChange}
            onNodeClick={(_, n) => select(n.id)}
            onEdgeClick={(_, e) => {
              setSelectedEdge(e.id);
              setSelectedId(null);
            }}
            nodesConnectable={false}
            edgesReconnectable={false}
            deleteKeyCode={null}
            fitView
            fitViewOptions={{ padding: 0.18, minZoom: 0.18, maxZoom: 1 }}
            minZoom={0.08}
            maxZoom={2}
            aria-label="مخطط خطة العميل"
          >
            <AutoFit layoutKey={`${view}-${pageId}-${flowId}-${search}`} />
            <Background color="#dddfea" gap={22} />
            <Controls showInteractive={false} />
            <MiniMap nodeColor={(n) => KIND_COLORS[(n.data as GraphNode).kind]} pannable zoomable />
          </ReactFlow>
          {nodes.length === 0 && (
            <p className="pm-empty">
              {graph.nodes.length
                ? "ماكو عناصر تطابق البحث"
                : "كمل تفاصيل الفكرة حتى تتبني صفحات المشروع وميزاته"}
            </p>
          )}
        </div>
        <Details
          node={selected}
          edge={graph.edges.find((e) => e.id === selectedEdge)}
          graph={graph}
          onSelect={select}
        />
      </div>
      <footer className="pm-footer" dir="rtl">
        <span>
          <i />
          من الخطة <i className="is-proposed" />
          اقتراح / مرجع من الوصف
        </span>
        <span>
          {graph.nodes.length} عنصر · {graph.edges.length} ارتباط
        </span>
        <div>
          <select
            aria-label="نطاق التصدير"
            value={exportScope}
            onChange={(e) => setExportScope(e.target.value)}
          >
            <option value="all">كل المخطط</option>
            <option value="view">العرض الحالي</option>
          </select>
          <select
            aria-label="نوع التصدير"
            value={exportFormat}
            onChange={(e) => setExportFormat(e.target.value as typeof exportFormat)}
          >
            <option value="json">JSON · مخطط كامل</option>
            <option value="svg">SVG · صورة المخطط</option>
            <option value="n8n">n8n · مخطط مواصفات</option>
          </select>
          <FinoraButton size="sm" loading={exporting} onClick={() => void exportMap()}>
            تصدير
          </FinoraButton>
          {src.createProjectConnection && (
            <FinoraButton size="sm" variant="ghost" onClick={() => setConnection(true)}>
              <Plug size={14} />
              ربط MCP
            </FinoraButton>
          )}
        </div>
      </footer>
      {exportFormat === "n8n" && (
        <p className="pm-export-note" dir="rtl">
          ملف n8n يرسم مواصفات المشروع بعناصر غير مفعّلة. التشغيل يحتاج بناء التكاملات.
        </p>
      )}
      {connection && <ConnectionPanel conversationId={conversationId} onClose={() => setConnection(false)} />}
    </>
  );
}

function ProjectMapDialog({ conversationId, onClose }: { conversationId: string; onClose: () => void }) {
  const src = useSource(),
    ref = useRef<HTMLDialogElement>(null);
  const query = useQuery({
    queryKey: ["project-graph", conversationId],
    queryFn: async () => {
      if (!src.getProjectGraph) throw new Error("المخطط غير متاح بهذا المصدر");
      return src.getProjectGraph(conversationId);
    },
    staleTime: 0,
    retry: false,
  });
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog ref={ref} className="pm-dialog" aria-label="مخطط خطة العميل" onCancel={onClose}>
      <header className="pm-header" dir="rtl">
        <div>
          <span className="pm-kicker">
            <Network size={16} />
            خريطة المشروع
          </span>
          <h2>{query.data?.title ?? "خطة العميل"}</h2>
          <p>الصفحات، الميزات، البيانات ومسارات العمل · نسخة {query.data?.revision ?? "…"}</p>
        </div>
        <button aria-label="إغلاق المخطط" onClick={onClose}>
          <X size={22} />
        </button>
      </header>
      {query.isPending ? (
        <p className="pm-loading" role="status">
          جاري تحميل المخطط…
        </p>
      ) : query.error ? (
        <div className="pm-loading" role="alert">
          <p>{errorText(query.error)}</p>
          <FinoraButton size="sm" onClick={() => void query.refetch()}>
            إعادة المحاولة
          </FinoraButton>
        </div>
      ) : (
        query.data && <Board key={query.data.planHash} graph={query.data} conversationId={conversationId} />
      )}
    </dialog>
  );
}

export function ProjectMapLauncher({ conversationId }: { conversationId: string }) {
  const src = useSource(),
    allowed = useCan("settings.manage"),
    [open, setOpen] = useState(false);
  if (!allowed || !src.getProjectGraph) return null;
  return (
    <>
      <FinoraButton size="sm" variant="ghost" className="pm-launch" onClick={() => setOpen(true)}>
        <Network size={16} />
        فتح مخطط الصفحات والميزات
      </FinoraButton>
      {open && <ProjectMapDialog conversationId={conversationId} onClose={() => setOpen(false)} />}
    </>
  );
}
