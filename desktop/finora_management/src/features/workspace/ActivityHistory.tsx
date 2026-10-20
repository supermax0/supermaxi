import { useQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import { useState } from "react";
import { workspaceApi } from "@/api/finora/workspace";
import { DialogShell } from "@/components/Dialog";
import { toast } from "@/stores/toasts";
import { openWorkspaceTarget } from "./navigation";
import { Skeleton, Retry, Empty } from "./WorkspacePrimitives";
export function ActivityHistory({ identity, onClose }: { identity: string; onClose(): void }) {
  const [pages, setPages] = useState<Awaited<ReturnType<typeof workspaceApi.activity>>["value"]["rows"]>([]);
  const [before, setBefore] = useState(0);
  const query = useQuery({
    queryKey: ["workspace", "activity", identity, before],
    queryFn: () => workspaceApi.activity(before),
    placeholderData: undefined,
  });
  const rows = [...pages, ...(query.data?.value.rows ?? [])];
  return (
    <DialogShell
      open
      title="سجل النشاط"
      onClose={onClose}
      footer={
        <>
          <button className="workspace-button" onClick={onClose}>
            إغلاق
          </button>
          {query.data?.value.has_more && (
            <button
              className="workspace-button"
              disabled={query.isFetching}
              onClick={() => {
                setPages(rows);
                const last = rows[rows.length - 1];
                if (last) setBefore(last.id);
              }}
            >
              عرض الأقدم
            </button>
          )}
        </>
      }
    >
      <div className="workspace-activity-history">
        {rows.map((row) => (
          <button
            key={row.id}
            className="workspace-list-row"
            onClick={() => {
              if (row.deleted) {
                toast.info("هذا السجل محذوف");
                return;
              }
              onClose();
              openWorkspaceTarget(row.target);
            }}
          >
            <span className="workspace-row-text">
              <strong>
                {row.title}
                {row.target.entityId ? ` #${row.target.entityId}` : ""}
              </strong>
              <small>
                {row.actor} · {new Date(row.at).toLocaleString("ar-IQ")}
              </small>
            </span>
            <ChevronLeft size={15} />
          </button>
        ))}
        {query.isPending && <Skeleton />}
        {query.isError && <Retry retry={query.refetch} />}
        {!query.isPending && !query.isError && !rows.length && <Empty>لا يوجد نشاط حديث لعرضه.</Empty>}
      </div>
    </DialogShell>
  );
}
