import { useMemo, useRef } from "react";
import { ArrowDownRight, ArrowUpRight, Download, ExternalLink, Printer } from "lucide-react";
import { formatNumber } from "@/utils/format";
import { openWorkspaceTarget } from "@/features/workspace/navigation";
import { rowTarget } from "./engine";
import { buildSourceModel, sourceCsv } from "./sourceModel";
import type { AssistantSource } from "./state";

const show = (value: unknown, money: boolean) =>
  typeof value === "number" ? `${formatNumber(value)}${money ? " د.ع" : ""}` : String(value ?? "—");

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
/** Prints only this card: everything else is hidden by the print stylesheet. */
function printCard(element: HTMLElement) {
  element.classList.add("assistant-print-target");
  document.body.classList.add("assistant-printing");
  const done = () => {
    element.classList.remove("assistant-print-target");
    document.body.classList.remove("assistant-printing");
    window.removeEventListener("afterprint", done);
  };
  window.addEventListener("afterprint", done);
  window.print();
}
export function SourceView({ source }: { source: AssistantSource }) {
  const model = useMemo(() => buildSourceModel(source.data), [source.data]);
  const card = useRef<HTMLDivElement>(null);
  if (!model.kpis.length && !model.bars.length && !model.table) return null;
  return (
    <div className="assistant-view" ref={card}>
      <h4 className="assistant-print-title">{source.title}</h4>
      {model.kpis.length > 0 && (
        <div className="assistant-kpis">
          {model.kpis.map((kpi) => (
            <div className="assistant-kpi" key={kpi.key}>
              <small>{kpi.label}</small>
              <strong className="ltr-isolate">{show(kpi.value, kpi.money)}</strong>
              {kpi.previous !== undefined && (
                <span
                  className={`assistant-change ${kpi.change == null ? "" : kpi.change >= 0 ? "is-up" : "is-down"}`}
                >
                  {kpi.change == null ? null : kpi.change >= 0 ? (
                    <ArrowUpRight size={12} />
                  ) : (
                    <ArrowDownRight size={12} />
                  )}
                  {kpi.change == null ? "لا مقارنة" : `${Math.abs(kpi.change)}%`}
                  <em className="ltr-isolate">قبل: {show(kpi.previous, kpi.money)}</em>
                </span>
              )}
            </div>
          ))}
        </div>
      )}
      {model.bars.map((group) => {
        const max = Math.max(1, ...group.items.map((i) => Math.abs(i.value)));
        return (
          <section className="assistant-bars" key={group.title} aria-label={group.title}>
            <small>{group.title}</small>
            {group.items.map((item) => (
              <div className="assistant-bar" key={item.label}>
                <span>{item.label}</span>
                <i style={{ inlineSize: `${Math.round((Math.abs(item.value) / max) * 100)}%` }} />
                <b className="ltr-isolate">{show(item.value, item.money)}</b>
              </div>
            ))}
          </section>
        );
      })}
      {model.table && (
        <div className="assistant-table">
          <table>
            <thead>
              <tr>
                {model.table.columns.map((c) => (
                  <th key={c.key}>{c.label}</th>
                ))}
                <th aria-label="فتح" />
              </tr>
            </thead>
            <tbody>
              {model.table.rows.map((row, index) => {
                const target = rowTarget(source, row);
                return (
                  <tr key={index}>
                    {model.table?.columns.map((c) => (
                      <td key={c.key} dir="auto">
                        {show(row[c.key], c.money)}
                      </td>
                    ))}
                    <td>
                      {target && "entityId" in target && (
                        <button
                          className="workspace-button"
                          aria-label="فتح السجل"
                          onClick={() => openWorkspaceTarget(target)}
                        >
                          <ExternalLink size={12} />
                          فتح
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="assistant-view-actions">
        <button
          className="workspace-button"
          onClick={() => download(`FINORA-${source.name}.csv`, sourceCsv(source.title, model))}
        >
          <Download size={13} />
          تصدير Excel
        </button>
        <button className="workspace-button" onClick={() => card.current && printCard(card.current)}>
          <Printer size={13} />
          طباعة
        </button>
      </div>
    </div>
  );
}
