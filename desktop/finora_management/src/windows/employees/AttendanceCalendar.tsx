import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { finora, toFinoraError } from "@/api/finora";
import { hrInput, hrToday, labels } from "./shared";
export function AttendanceCalendar({ personId }: { personId: number }) {
  const [month, setMonth] = useState(hrToday().slice(0, 7));
  const [week, setWeek] = useState(0);
  const calendar = useQuery({
    queryKey: ["hr", "calendar", personId, month],
    queryFn: () => finora.hr.calendar(personId, month),
  });
  const rows = calendar.data?.rows ?? [];
  const offset = rows[0] ? (new Date(rows[0].date + "T12:00:00Z").getUTCDay() + 6) % 7 : 0;
  const cells = [...Array.from({ length: offset }, () => null), ...rows];
  const shown = week ? cells.slice((week - 1) * 7, week * 7) : cells;
  return (
    <section className="rounded-panel border border-line/70 p-4" aria-label="تقويم دوام الموظف">
      <h3 className="text-xs font-semibold">تقويم الدوام</h3>
      <div className="mt-3 flex gap-2">
        <input
          className={hrInput}
          aria-label="شهر تقويم الدوام"
          type="month"
          value={month}
          onChange={(e) => {
            setMonth(e.target.value);
            setWeek(0);
          }}
        />
        <select
          className={hrInput}
          aria-label="طريقة عرض تقويم الدوام"
          value={week}
          onChange={(e) => setWeek(Number(e.target.value))}
        >
          <option value={0}>الشهر كامل</option>
          {Array.from({ length: Math.ceil(cells.length / 7) }, (_, i) => (
            <option key={i + 1} value={i + 1}>
              الأسبوع {i + 1}
            </option>
          ))}
        </select>
      </div>
      {calendar.isLoading && <p className="mt-3 text-xs text-ink-faint">تحميل الدوام…</p>}
      {calendar.error && (
        <p role="alert" className="mt-3 text-xs text-danger">
          {toFinoraError(calendar.error).message}
        </p>
      )}
      <div className="mt-3 grid grid-cols-7 gap-1" dir="rtl">
        {["اث", "ثل", "أر", "خم", "جم", "سب", "أح"].map((d) => (
          <span key={d} className="text-center text-[10px] text-ink-faint">
            {d}
          </span>
        ))}
        {shown.map((day, index) =>
          day ? (
            <div
              key={day.date}
              title={[
                day.date,
                labels[day.state] ?? day.state,
                day.shift?.name,
                day.holiday,
                day.check_in && `${day.check_in} — ${day.check_out || "لم ينصرف"}`,
                day.leave_days ? `إجازة ${day.leave_days} يوم` : "",
              ]
                .filter(Boolean)
                .join(" · ")}
              className={`min-h-[62px] rounded-control border p-1 text-center text-[10px] ${day.state === "absent" ? "border-danger/10 bg-danger-soft text-danger" : day.state === "present" || day.state === "late" ? "border-success/10 bg-success-soft text-success" : day.state === "holiday" ? "border-line/50 bg-white text-ink-faint" : "border-violet/10 bg-violet-soft/30 text-violet"}`}
            >
              <strong className="block text-xs">{Number(day.date.slice(-2))}</strong>
              <span className="mt-1 block leading-4">{labels[day.state] ?? day.state}</span>
              {day.leave_days > 0 && day.state !== "leave" && <span>إجازة {day.leave_days}</span>}
            </div>
          ) : (
            <span key={`blank-${index}`} />
          ),
        )}
      </div>
      <p className="mt-3 text-[10px] leading-5 text-ink-faint">
        مرّر المؤشر لعرض الوردية والساعات. بدون نت تُعرض الأشهر التي فتحتها وحُفظت على هذا الجهاز.
      </p>
    </section>
  );
}
