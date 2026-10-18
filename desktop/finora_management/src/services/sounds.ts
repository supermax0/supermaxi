import { useSoundPreferences } from "@/stores/soundPreferences";

export type SoundCue =
  "click" | "typing" | "toggle" | "open" | "close" | "success" | "error" | "warning" | "notify" | "scan";
interface Note {
  frequency: number;
  end?: number;
  at: number;
  length: number;
  gain: number;
}
/** Original, soft sine and glass tones; no external assets or OS sound files. */
export const SOUND_NOTES: Record<SoundCue, readonly Note[]> = {
  typing: [{ frequency: 720, end: 320, at: 0, length: 0.028, gain: 0.045 }],
  click: [
    { frequency: 920, end: 460, at: 0, length: 0.055, gain: 0.15 },
    { frequency: 1840, end: 1200, at: 0, length: 0.025, gain: 0.025 },
  ],
  toggle: [{ frequency: 740, end: 1046, at: 0, length: 0.065, gain: 0.13 }],
  open: [
    { frequency: 392, end: 523, at: 0, length: 0.1, gain: 0.11 },
    { frequency: 784, end: 1046, at: 0.012, length: 0.09, gain: 0.035 },
  ],
  close: [{ frequency: 523, end: 330, at: 0, length: 0.085, gain: 0.1 }],
  success: [
    { frequency: 659, at: 0, length: 0.16, gain: 0.12 },
    { frequency: 988, at: 0.07, length: 0.2, gain: 0.09 },
    { frequency: 1976, at: 0.075, length: 0.13, gain: 0.022 },
  ],
  error: [
    { frequency: 440, at: 0, length: 0.13, gain: 0.12 },
    { frequency: 349, at: 0.09, length: 0.17, gain: 0.1 },
  ],
  warning: [
    { frequency: 587, at: 0, length: 0.12, gain: 0.1 },
    { frequency: 587, at: 0.15, length: 0.15, gain: 0.075 },
  ],
  notify: [
    { frequency: 784, at: 0, length: 0.17, gain: 0.08 },
    { frequency: 1175, at: 0.085, length: 0.21, gain: 0.075 },
  ],
  scan: [
    { frequency: 1046, at: 0, length: 0.07, gain: 0.12 },
    { frequency: 1568, at: 0.045, length: 0.11, gain: 0.07 },
  ],
};
export function scheduleSound(
  context: BaseAudioContext,
  cue: SoundCue,
  volume: number,
  at = context.currentTime,
) {
  const master = context.createGain();
  master.gain.setValueAtTime(Math.max(0, Math.min(1, volume / 100)), at);
  master.connect(context.destination);
  const notes = SOUND_NOTES[cue];
  let remaining = notes.length;
  for (const note of notes) {
    const oscillator = context.createOscillator();
    const envelope = context.createGain();
    const start = at + note.at;
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(note.frequency, start);
    if (note.end) oscillator.frequency.exponentialRampToValueAtTime(note.end, start + note.length);
    envelope.gain.setValueAtTime(0.00001, start);
    envelope.gain.exponentialRampToValueAtTime(note.gain, start + 0.006);
    envelope.gain.exponentialRampToValueAtTime(0.00001, start + note.length);
    oscillator.connect(envelope).connect(master);
    oscillator.onended = () => {
      oscillator.disconnect();
      envelope.disconnect();
      if (--remaining === 0) master.disconnect();
    };
    oscillator.start(start);
    oscillator.stop(start + note.length + 0.008);
  }
  return master;
}
let context: AudioContext | null = null;
let armed = false;
let pending: ReturnType<typeof setTimeout> | undefined;
let lastPlayed = -Infinity;
let lastCue: SoundCue | null = null;
const voices: GainNode[] = [];
function unavailable(error: unknown) {
  if (import.meta.env.DEV) console.debug("[sound] audio unavailable", error);
}
/** Only user interaction unlocks audio; opening the app alone is silent. */
export function unlockSounds() {
  armed = true;
  const preferences = useSoundPreferences.getState();
  if (!preferences.enabled || preferences.volume === 0) return;
  try {
    if (typeof window.AudioContext !== "function") return;
    context ??= new AudioContext();
    if (context.state === "suspended") void context.resume().catch(unavailable);
  } catch (error) {
    unavailable(error);
  }
}
function play(cue: SoundCue) {
  const { enabled, typing, volume } = useSoundPreferences.getState();
  if (cue === "typing" && !typing) return;
  if (!armed || !enabled || volume === 0 || !context || context.state !== "running" || document.hidden)
    return;
  const now = performance.now();
  if ((cue === "click" || cue === "toggle" || cue === "open" || cue === "close") && now - lastPlayed < 65)
    return;
  if (cue !== "typing" && cue === lastCue && now - lastPlayed < 140) return;
  try {
    if (cue !== "typing") {
      lastPlayed = now;
      lastCue = cue;
    }
    const voice = scheduleSound(context, cue, volume);
    voices.push(voice);
    if (voices.length > 4) voices.shift()?.disconnect();
    setTimeout(() => {
      const index = voices.indexOf(voice);
      if (index >= 0) voices.splice(index, 1);
    }, 400);
  } catch (error) {
    unavailable(error);
  }
}
export function playSound(cue: SoundCue) {
  if (cue === "typing") {
    play(cue);
    return;
  }
  clearTimeout(pending);
  // Let a dialog/window transition replace its initiating click, not layer it.
  if (cue === "click" || cue === "toggle") pending = setTimeout(() => play(cue), 35);
  else play(cue);
}
useSoundPreferences.subscribe((state) => {
  if (state.enabled && state.volume > 0) return;
  clearTimeout(pending);
  for (const voice of voices.splice(0)) voice.disconnect();
});
