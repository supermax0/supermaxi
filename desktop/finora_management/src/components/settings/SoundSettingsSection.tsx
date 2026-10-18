import { Volume2, Play } from "lucide-react";
import { FeatureHelp } from "@/components/FeatureHelp";
import { playSound, unlockSounds, type SoundCue } from "@/services/sounds";
import { useSoundPreferences } from "@/stores/soundPreferences";
import { SectionCard, SettingRow, Switch } from "./primitives";
const samples: { cue: SoundCue; label: string }[] = [
  { cue: "click", label: "ضغطة" },
  { cue: "typing", label: "كتابة" },
  { cue: "open", label: "فتح" },
  { cue: "close", label: "إغلاق" },
  { cue: "success", label: "نجاح" },
  { cue: "warning", label: "تنبيه" },
  { cue: "error", label: "خطأ" },
  { cue: "scan", label: "باركود" },
];
export function SoundSettingsSection() {
  const { enabled, typing, volume, update } = useSoundPreferences();
  return (
    <SectionCard title="أصوات الواجهة" icon={Volume2}>
      <SettingRow
        title="أصوات الضغط والحركات"
        hint="أصوات قصيرة وناعمة للضغط والفتح والإغلاق ونتائج العمليات. تُحفظ على هذا الجهاز."
      >
        <Switch label="أصوات الواجهة" checked={enabled} onChange={(next) => update({ enabled: next })} />
      </SettingRow>
      <SettingRow
        title="صوت الكتابة"
        hint="نقرة خفيفة للحروف والمسح. تقدر تكتم الكتابة وحدها وتبقي بقية الأصوات."
      >
        <Switch
          label="صوت الكتابة"
          checked={typing}
          disabled={!enabled}
          onChange={(next) => update({ typing: next })}
        />
      </SettingRow>
      <SettingRow title="مستوى الصوت" hint="الكتم يشمل أصوات الواجهة والباركود. مستوى صفر يكتم الصوت أيضاً.">
        <div className="flex w-44 items-center gap-3" dir="ltr">
          <input
            type="range"
            min="0"
            max="100"
            step="5"
            aria-label="مستوى صوت الواجهة"
            value={volume}
            disabled={!enabled}
            onChange={(event) => update({ volume: Number(event.target.value) })}
            onPointerUp={() => {
              unlockSounds();
              playSound("click");
            }}
            className="min-w-0 flex-1 accent-violet disabled:opacity-40"
          />
          <output className="w-10 text-end text-sm font-semibold text-ink-soft">{volume}%</output>
        </div>
      </SettingRow>
      <div className="flex items-center justify-between gap-3 pt-3 text-sm font-medium text-ink-soft">
        <span>جرّب الأصوات</span>
        <FeatureHelp
          label="شرح أصوات الواجهة"
          text="الأصوات خفيفة ومحلية وتعمل بدون إنترنت. صوت الكتابة أخف من الأزرار ويشمل الحروف والمسح؛ يُكتم أثناء دفعات الباركود السريعة ولا يسجل النص المكتوب. تقدر تطفي الكتابة وحدها. المرور بالمؤشر صامت، ورسائل النجاح والخطأ تبقى ظاهرة. كتم الواجهة يكتم كل الأصوات، وإعداد الباركود الخاص يقدر يوقف صوت المسح وحده."
        />
      </div>
      <div className="grid grid-cols-3 gap-2 pb-4 pt-3">
        {samples.map((sample) => (
          <button
            key={sample.cue}
            type="button"
            data-sound="off"
            disabled={!enabled || volume === 0 || (sample.cue === "typing" && !typing)}
            onClick={() => {
              unlockSounds();
              playSound(sample.cue);
            }}
            aria-label={`تجربة صوت ${sample.label}`}
            className="flex h-10 items-center justify-center gap-2 rounded-control border border-line bg-white text-xs text-ink-soft transition-colors hover:bg-violet-soft hover:text-violet disabled:opacity-40"
          >
            <Play size={13} aria-hidden />
            {sample.label}
          </button>
        ))}
      </div>
    </SectionCard>
  );
}
