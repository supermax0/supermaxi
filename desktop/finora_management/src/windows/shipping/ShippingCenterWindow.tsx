import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Building2,
  FilePlus2,
  HandCoins,
  PackageCheck,
  PackageX,
  RefreshCw,
  Truck,
  UserRound,
} from "lucide-react";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "@/stores/toasts";
import { finora, toFinoraError } from "@/api/finora";
import { StatCard } from "@/components/StatCard";
import { StatusTabs } from "@/components/StatusTabs";
import { useConnection } from "@/stores/connection";
import { useCan } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";
import { supplierPrimary, supplierSecondary } from "../suppliers/SupplierDialogs";
import { NewSettlementDialog } from "./Dialogs";
import { DispatchDialog } from "./Dispatch";
import { OverduePanel } from "./Insights";
import { ManifestWorkspace } from "./ManifestWorkspace";
import { ReceiptsList } from "./Finance";
import { ManifestsSection } from "./Manifests";
import { ReturnsSection } from "./Returns";
import { ManifestMiniList, PartiesSection } from "./Parties";
import { Money, Panel, SECTIONS, type Section } from "./shared";

export function ShippingCenterWindow() {
  const active = useWindowManager((s) => s.active === "shipping");
  const allowed = useCan("can_see_shipping");
  const online = useConnection((s) => s.status === "online");
  const client = useQueryClient();
  const [section, setSection] = useState<Section>("overview");
  const [openManifest, setOpenManifest] = useState<number | null>(null);
  const [dialog, setDialog] = useState<"settlement" | "handover" | null>(null);
  const [settlementView, setSettlementView] = useState<"receipts" | "manifests">("receipts");
  const fromPortal = useMutation({
    mutationFn: (agentId: number) =>
      finora.shipping.createSettlement({
        agent_id: agentId,
        from_portal: true,
        reference: "",
        date: new Date().toISOString().slice(0, 10),
      }),
    onSuccess: async (res) => {
      toast.success(`أُنشئ ${res.manifest.number} من كشف البوابة — راجع التصنيف قبل الاعتماد`);
      await client.invalidateQueries({ queryKey: ["shipping"] });
      setOpenManifest(res.manifest.id);
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });

  const meta = useQuery({
    queryKey: ["shipping", "meta"],
    queryFn: () => finora.shipping.meta(),
    enabled: active && allowed,
    staleTime: 60_000,
  });
  const carriers = meta.data?.carriers ?? [];
  const canManage = meta.data?.can_manage ?? false;

  if (!allowed) {
    return (
      <div className="grid h-full place-items-center text-center">
        <div>
          <p className="text-lg font-semibold text-ink">لا تملك صلاحية مركز الشحن</p>
          <p className="mt-1 text-sm text-ink-faint">اطلب من مدير النظام منحك صلاحية «عرض الشحن».</p>
        </div>
      </div>
    );
  }

  if (openManifest != null) {
    return (
      <ManifestWorkspace
        key={openManifest}
        manifestId={openManifest}
        canApprove={meta.data?.can_approve ?? false}
        canManage={canManage}
        treasuryAccounts={meta.data?.treasury_accounts ?? []}
        onBack={() => setOpenManifest(null)}
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-4 flex shrink-0 flex-wrap items-center gap-3">
        <StatusTabs<Section> label="أقسام مركز الشحن" value={section} tabs={SECTIONS} onChange={setSection} />
        <div className="ms-auto flex items-center gap-2">
          <button
            type="button"
            aria-label="تحديث"
            className={cn(supplierSecondary, "w-11 px-0")}
            disabled={!online}
            onClick={() => void client.invalidateQueries({ queryKey: ["shipping"] })}
          >
            <RefreshCw size={17} />
          </button>
          {canManage && (
            <>
              <button
                type="button"
                className={supplierSecondary}
                disabled={!online || (carriers.length === 0 && (meta.data?.agents ?? []).length === 0)}
                onClick={() => setDialog("handover")}
              >
                <PackageCheck size={17} /> تسليم وإسناد
              </button>
              <button
                type="button"
                className={supplierPrimary}
                disabled={!online || carriers.length === 0}
                onClick={() => setDialog("settlement")}
              >
                <FilePlus2 size={17} /> كشف تسوية جديد
              </button>
            </>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1">
        {section === "overview" && (
          <Overview enabled={active} onOpen={setOpenManifest} onSection={setSection} />
        )}
        {section === "carriers" && (
          <PartiesSection
            owner="carriers"
            enabled={active}
            onOpenManifest={setOpenManifest}
            meta={meta.data}
          />
        )}
        {section === "agents" && (
          <PartiesSection
            owner="agents"
            enabled={active}
            onOpenManifest={setOpenManifest}
            meta={meta.data}
            onPortalSettlement={(agentId) => fromPortal.mutate(agentId)}
          />
        )}
        {section === "manifests" && (
          <ManifestsSection enabled={active} carriers={carriers} onOpen={setOpenManifest} />
        )}
        {section === "settlements" && (
          <div className="flex h-full min-h-0 flex-col">
            <div className="mb-3 shrink-0">
              <StatusTabs<"receipts" | "manifests">
                label="التسويات المالية"
                value={settlementView}
                onChange={setSettlementView}
                tabs={[
                  { id: "receipts", label: "سندات القبض" },
                  { id: "manifests", label: "كشوف التسوية المعتمدة" },
                ]}
              />
            </div>
            <div className="min-h-0 flex-1">
              {settlementView === "receipts" ? (
                <ReceiptsList enabled={active} />
              ) : (
                <ManifestsSection
                  key="settlements"
                  enabled={active}
                  settlementsOnly
                  carriers={carriers}
                  onOpen={setOpenManifest}
                />
              )}
            </div>
          </div>
        )}
        {section === "returns" && <ReturnsSection enabled={active} canManage={canManage} />}
      </div>

      {dialog === "settlement" && (
        <NewSettlementDialog
          carriers={carriers}
          agents={meta.data?.agents ?? []}
          onClose={() => setDialog(null)}
          onCreated={(id) => {
            setDialog(null);
            setOpenManifest(id);
          }}
        />
      )}
      {dialog === "handover" && (
        <DispatchDialog
          carriers={carriers}
          agents={meta.data?.agents ?? []}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  );
}

function Overview({
  enabled,
  onOpen,
  onSection,
}: {
  enabled: boolean;
  onOpen(id: number): void;
  onSection(section: Section): void;
}) {
  const overview = useQuery({
    queryKey: ["shipping", "overview"],
    queryFn: () => finora.shipping.overview(),
    enabled,
  });
  const carriers = useQuery({
    queryKey: ["shipping", "carriers"],
    queryFn: async () => (await finora.shipping.carriers()).rows,
    enabled,
  });
  const open = useQuery({
    queryKey: ["shipping", "manifests", { state: "open", kind: "settlement", search: "", carrierId: null }],
    queryFn: () => finora.shipping.manifests({ state: "open", kind: "settlement", search: "" }),
    enabled,
  });
  const cards = overview.data?.cards;
  const loading = overview.isPending;
  const topCarriers = [...(carriers.data ?? [])].sort((a, b) => b.due - a.due).slice(0, 6);
  const maxDue = Math.max(1, ...topCarriers.map((c) => c.due));

  if (overview.error) {
    return <p className="py-10 text-center text-sm text-danger">{toFinoraError(overview.error).message}</p>;
  }
  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="grid shrink-0 grid-cols-3 gap-3">
        <StatCard
          label="قيد التوصيل"
          value={formatNumber(cards?.in_transit.count ?? 0)}
          unit="طلب"
          icon={Truck}
          tone="azure"
          loading={loading}
          onClick={() => onSection("carriers")}
        />
        <StatCard
          label={`تم التوصيل وغير مسدد (${formatNumber(cards?.delivered_unsettled.count ?? 0)})`}
          value={formatNumber(cards?.delivered_unsettled.amount ?? 0)}
          unit="د.ع"
          icon={PackageCheck}
          tone="warning"
          loading={loading}
          onClick={() => onSection("carriers")}
        />
        <StatCard
          label="مستحقات شركات النقل"
          value={formatNumber(cards?.carriers_due.amount ?? 0)}
          unit="د.ع"
          icon={Building2}
          tone="violet"
          loading={loading}
          onClick={() => onSection("carriers")}
        />
        <StatCard
          label="مستحقات المندوبين"
          value={formatNumber(cards?.agents_due.amount ?? 0)}
          unit="د.ع"
          icon={UserRound}
          tone="success"
          loading={loading}
          onClick={() => onSection("agents")}
        />
        <StatCard
          label="المرتجعات"
          value={formatNumber(cards?.returns.count ?? 0)}
          unit="طلب"
          icon={PackageX}
          tone="danger"
          loading={loading}
          onClick={() => onSection("returns")}
        />
        <StatCard
          label={`كشوف مفتوحة · ${formatNumber(cards?.open_manifests.flagged ?? 0)} طلب بمشكلة`}
          value={formatNumber(cards?.open_manifests.count ?? 0)}
          unit="كشف"
          icon={AlertTriangle}
          tone="neutral"
          loading={loading}
          onClick={() => onSection("manifests")}
        />
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-3 gap-4">
        <Panel title="كشوف تسوية بانتظار الاعتماد" icon={HandCoins} className="overflow-hidden">
          <div className="min-h-0 flex-1 overflow-y-auto">
            <ManifestMiniList rows={(open.data?.rows ?? []).slice(0, 12)} onOpen={onOpen} />
          </div>
        </Panel>
        <Panel title="أعلى المستحقات حسب الشركة" icon={Building2} className="overflow-hidden">
          <ul className="min-h-0 flex-1 space-y-3 overflow-y-auto">
            {topCarriers.length === 0 && (
              <li className="py-8 text-center text-[13px] text-ink-faint">لا توجد بيانات</li>
            )}
            {topCarriers.map((c) => (
              <li key={c.id}>
                <div className="flex items-center justify-between gap-2 text-[13px]">
                  <span className="truncate font-medium">{c.name}</span>
                  <Money value={c.due} className="font-bold text-maroon" />
                </div>
                <span className="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-surface-sunken">
                  <span
                    className="block h-full rounded-full bg-maroon"
                    style={{ width: `${(c.due / maxDue) * 100}%` }}
                  />
                </span>
                <p className="mt-1 text-[11px] text-ink-faint">
                  {formatNumber(c.stats.transit.count)} قيد التوصيل ·{" "}
                  {formatNumber(c.stats.delivered_unsettled.count)} واصل غير مسدد
                </p>
              </li>
            ))}
          </ul>
        </Panel>
        <OverduePanel enabled={enabled} onOpenManifest={onOpen} onSection={onSection} />
      </div>
    </div>
  );
}
