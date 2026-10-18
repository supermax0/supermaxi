import {
  Building2,
  ChevronLeft,
  CircleCheck,
  Circle,
  Globe2,
  Mail,
  MapPin,
  Pencil,
  Phone,
  Stethoscope,
  UserRound,
  UsersRound,
  X,
  type LucideIcon,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { useCan } from "../data/can";
import { useAddNote, useCustomer } from "../data/hooks";
import { CustomerProject } from "./ProjectPlan";
import type { CustomerProfile, ProfileFieldKey } from "../data/schemas";
import { useUi } from "../state/ui";
import { AccountSetup } from "./AccountSetup";
import { toast } from "../ui/toast";
import {
  Avatar,
  CHANNEL_LABEL,
  ChannelIcon,
  ErrorState,
  FinoraButton,
  IconButton,
  LeadBadge,
  MiniOrb,
  Skeleton,
  Time,
  errorText,
} from "../ui/primitives";

/** Below this confidence a fact is treated as unknown (spec §13, §80: never display guesses). */
const MIN_CONFIDENCE = 0.6;

const FIELDS: { key: ProfileFieldKey; label: string; icon: LucideIcon; always: boolean }[] = [
  { key: "businessType", label: "نوع النشاط", icon: Building2, always: true },
  { key: "specialty", label: "التخصص", icon: Stethoscope, always: false },
  { key: "doctors", label: "عدد الأطباء", icon: UserRound, always: true },
  { key: "employees", label: "عدد الموظفين", icon: UsersRound, always: true },
  { key: "branches", label: "عدد الفروع", icon: MapPin, always: true },
  { key: "country", label: "الدولة", icon: Globe2, always: true },
  { key: "city", label: "المدينة", icon: MapPin, always: false },
  { key: "phone", label: "الهاتف", icon: Phone, always: false },
  { key: "email", label: "البريد", icon: Mail, always: false },
];

function Facts({ p }: { p: CustomerProfile }) {
  return (
    <dl className="cp-facts">
      {FIELDS.map(({ key, label, icon: Icon, always }) => {
        const f = p.facts[key];
        const known = f && f.confidence >= MIN_CONFIDENCE;
        if (!known && !always) return null;
        return (
          <div className="cp-fact" key={key}>
            <dt>
              <Icon size={18} aria-hidden="true" />
              {label}
            </dt>
            <dd
              className={known ? undefined : "is-unknown"}
              dir={key === "phone" || key === "email" ? "ltr" : undefined}
            >
              {known ? String(f.value) : "غير محدد"}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

function Notes({ conversationId, p }: { conversationId: string; p: CustomerProfile }) {
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const add = useAddNote(conversationId);
  const canWrite = useCan("notes.write");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body = draft.trim();
    if (!body) return;
    add.mutate(body, {
      onSuccess: () => {
        setDraft("");
        setEditing(false);
      },
      onError: (err) => toast.error(errorText(err)),
    });
  };
  return (
    <section className="cp-card cp-notes" aria-labelledby="cp-notes-h">
      <header className="cp-card-head">
        <h3 id="cp-notes-h">
          ملاحظات <span className="internal-tag">داخلية</span>
        </h3>
        {canWrite && (
          <IconButton label="إضافة ملاحظة" onClick={() => setEditing((v) => !v)}>
            <Pencil size={15} />
          </IconButton>
        )}
      </header>
      {editing && (
        <form onSubmit={submit} className="cp-note-form">
          <textarea
            autoFocus
            rows={2}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="ملاحظة لا يراها العميل"
            aria-label="ملاحظة داخلية"
            maxLength={1000}
          />
          <FinoraButton
            type="submit"
            variant="primary"
            size="sm"
            loading={add.isPending}
            disabled={!draft.trim()}
          >
            حفظ
          </FinoraButton>
        </form>
      )}
      {p.notes.length === 0 && !editing ? (
        <p className="cp-muted">لا توجد ملاحظات</p>
      ) : (
        <ul className="cp-note-list">
          {p.notes.map((n) => (
            <li key={n.id}>
              <p dir="auto">{n.body}</p>
              <span className="cp-note-meta">
                {n.author} · <Time iso={n.at} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function CustomerPanel() {
  const id = useUi((s) => s.selectedConversationId);
  const toggle = useUi((s) => s.toggleCustomerPanel);
  const q = useCustomer(id);

  return (
    <aside className="cp" aria-labelledby="cp-title">
      <header className="cp-head">
        <h2 id="cp-title">ملف العميل</h2>
        <IconButton label="إغلاق ملف العميل" onClick={() => toggle(false)}>
          <X size={18} />
        </IconButton>
      </header>

      <div className="cp-scroll">
        {!id ? null : q.isPending ? (
          <div className="cp-skel" aria-busy="true">
            <Skeleton w={72} h={72} r={36} />
            <Skeleton w="60%" h={14} />
            <Skeleton w="100%" h={180} r={16} />
            <Skeleton w="100%" h={90} r={16} />
          </div>
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : (
          <>
            <section className="cp-profile">
              <Avatar name={q.data.name} url={q.data.avatarUrl} size={72} />
              <div className="cp-id">
                <strong>
                  <bdi>{q.data.name}</bdi>
                </strong>
                <span className="cp-channel">
                  <ChannelIcon channel={q.data.channel} size={16} />
                  {CHANNEL_LABEL[q.data.channel]}
                </span>
                <LeadBadge stage={q.data.leadStage} />
              </div>
            </section>

            <section className="cp-card">
              <Facts p={q.data} />
            </section>

            <section className="cp-card" aria-labelledby="cp-plan-h">
              <header className="cp-card-head">
                <h3 id="cp-plan-h">الباقة المقترحة</h3>
              </header>
              {q.data.recommendedPlan ? (
                <div className="cp-plan">
                  <MiniOrb size={52} />
                  <span className="cp-plan-text">
                    <strong dir="ltr">{q.data.recommendedPlan.name}</strong>
                    <span>{q.data.recommendedPlan.tier}</span>
                  </span>
                  <ChevronLeft size={18} className="cp-chevron" aria-hidden="true" />
                </div>
              ) : (
                <p className="cp-muted">لم تُحدد بعد — تحتاج معلومات أكثر عن النشاط</p>
              )}
            </section>

            <section className="cp-card" aria-labelledby="cp-steps-h">
              <header className="cp-card-head">
                <h3 id="cp-steps-h">الإجراءات التالية</h3>
              </header>
              <ol className="cp-steps">
                {q.data.onboarding.map((s) => (
                  <li key={s.key} className={s.done ? "is-done" : undefined}>
                    {s.done ? (
                      <CircleCheck size={22} aria-label="مكتمل" />
                    ) : (
                      <Circle size={22} aria-label="غير مكتمل" />
                    )}
                    {s.label}
                  </li>
                ))}
              </ol>
            </section>

            {id && q.data.project && (
              <CustomerProject key={`project-${id}`} project={q.data.project} conversationId={id} />
            )}
            {id && <Notes conversationId={id} p={q.data} />}
            {id && <AccountSetup key={id} conversationId={id} tenantSlug={q.data.finoraTenantId} />}
          </>
        )}
      </div>
    </aside>
  );
}
