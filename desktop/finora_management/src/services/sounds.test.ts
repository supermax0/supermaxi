import { SOUND_STORAGE_KEY, readSoundPreferences, useSoundPreferences } from "@/stores/soundPreferences";

const ramp = () => ({ setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() });
function contextFixture() {
  const oscillators: {
    start: ReturnType<typeof vi.fn>;
    stop: ReturnType<typeof vi.fn>;
    frequency: ReturnType<typeof ramp>;
  }[] = [];
  const gains: { disconnect: ReturnType<typeof vi.fn>; gain: ReturnType<typeof ramp> }[] = [];
  const context = {
    currentTime: 1,
    destination: {},
    state: "running",
    resume: vi.fn().mockResolvedValue(undefined),
    createGain: vi.fn(() => {
      const node = { gain: ramp(), connect: vi.fn().mockReturnThis(), disconnect: vi.fn() };
      gains.push(node);
      return node;
    }),
    createOscillator: vi.fn(() => {
      const node = {
        type: "",
        frequency: ramp(),
        connect: vi.fn().mockReturnThis(),
        disconnect: vi.fn(),
        start: vi.fn(),
        stop: vi.fn(),
        onended: null,
      };
      oscillators.push(node);
      return node;
    }),
  };
  vi.stubGlobal(
    "AudioContext",
    vi.fn(function () {
      return context;
    }),
  );
  return { context, oscillators, gains };
}
beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
  useSoundPreferences.setState({ enabled: true, typing: true, volume: 30 });
  localStorage.removeItem(SOUND_STORAGE_KEY);
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("silence before interaction, click-to-window deduplication and bounded rapid clicks", async () => {
  const { oscillators, gains } = contextFixture();
  const sound = await import("./sounds");
  // resetModules gives the sound module its own store instance.
  const preferences = await import("@/stores/soundPreferences");
  preferences.useSoundPreferences.setState({ enabled: true, volume: 30 });
  sound.playSound("success");
  expect(oscillators).toHaveLength(0);
  sound.unlockSounds();
  sound.playSound("click");
  sound.playSound("open");
  vi.advanceTimersByTime(40);
  expect(oscillators).toHaveLength(sound.SOUND_NOTES.open.length);
  expect(gains[0]?.gain.setValueAtTime).toHaveBeenCalledWith(0.3, 1);
  for (let i = 0; i < 20; i++) sound.playSound("click");
  vi.advanceTimersByTime(40);
  expect(oscillators).toHaveLength(sound.SOUND_NOTES.open.length);
  preferences.useSoundPreferences.getState().update({ enabled: false });
  expect(gains[0]?.disconnect).toHaveBeenCalled();
  vi.advanceTimersByTime(200);
  sound.playSound("error");
  expect(oscillators).toHaveLength(sound.SOUND_NOTES.open.length);
});

test("audio failures never throw or change an operation", async () => {
  vi.stubGlobal(
    "AudioContext",
    vi.fn(function () {
      throw Error("No audio device");
    }),
  );
  const sound = await import("./sounds");
  expect(() => {
    sound.unlockSounds();
    sound.playSound("error");
  }).not.toThrow();
  vi.advanceTimersByTime(100);
});

test("sound preferences persist independently, clamp volume and accept legacy missing values", () => {
  localStorage.setItem("finora-management:preferences", '{"motion":"reduced"}');
  useSoundPreferences.getState().update({ volume: 500, enabled: false });
  expect(readSoundPreferences()).toEqual({ volume: 100, enabled: false, typing: true });
  useSoundPreferences.getState().update({ typing: false });
  expect(readSoundPreferences().typing).toBe(false);
  expect(localStorage.getItem("finora-management:preferences")).toBe('{"motion":"reduced"}');
  useSoundPreferences.getState().update({ volume: NaN });
  expect(readSoundPreferences().volume).toBe(100);
  localStorage.setItem(SOUND_STORAGE_KEY, "null");
  expect(readSoundPreferences()).toEqual({ volume: 30, enabled: true, typing: true });
  localStorage.setItem(SOUND_STORAGE_KEY, '{"enabled":false,"volume":45}');
  expect(readSoundPreferences()).toEqual({ volume: 45, enabled: false, typing: true });
});

test("typing has no click throttle and can be muted independently without muting results", async () => {
  const { oscillators } = contextFixture();
  const sound = await import("./sounds");
  const { useSoundPreferences: preferences } = await import("@/stores/soundPreferences");
  preferences.setState({ enabled: true, typing: true, volume: 30 });
  sound.unlockSounds();
  for (let i = 0; i < 4; i++) {
    sound.playSound("typing");
    vi.advanceTimersByTime(70);
  }
  expect(oscillators).toHaveLength(4);
  preferences.getState().update({ typing: false });
  sound.playSound("typing");
  expect(oscillators).toHaveLength(4);
  sound.playSound("success");
  expect(oscillators).toHaveLength(4 + sound.SOUND_NOTES.success.length);
  preferences.getState().update({ enabled: false, typing: true });
  sound.playSound("typing");
  expect(oscillators).toHaveLength(4 + sound.SOUND_NOTES.success.length);
});
