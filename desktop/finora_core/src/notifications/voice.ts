import { z } from "zod";
import type { CoreEvent } from "../data/schemas";
import { CoreError } from "../data/source";
import { useSound } from "./preferences";

export const liveSessionSchema = z.object({
  session: z.object({ id: z.string().min(1) }),
  transport: z.object({ type: z.literal("webrtc"), sdp: z.string().startsWith("v=0") }),
  announcement: z.string().min(1).max(300),
  model: z.literal("gpt-live-1"),
});
export type LiveSession = z.infer<typeof liveSessionSchema>;
export type Notice = { kind: "approval" | "support" | "delivery" | "test"; ref?: string; key: string };
export function noticeFor(event: CoreEvent): Notice | null {
  if (event.type === "approval.required" && event.approval.status === "pending")
    return { kind: "approval", ref: event.approval.id, key: `approval:${event.approval.id}` };
  if (event.type === "support.issue" && event.issue.status === "open")
    return { kind: "support", ref: event.issue.id, key: `support:${event.issue.id}` };
  if (
    (event.type === "message.updated" || event.type === "message.sent") &&
    (event.message.sender === "core" || event.message.sender === "human") &&
    event.message.delivery === "failed"
  )
    return { kind: "delivery", ref: event.message.id, key: `delivery:${event.message.id}` };
  return null;
}
type StartSession = (notice: Notice, sdp: string, signal: AbortSignal) => Promise<LiveSession>;

/** One bounded, output-only Live session at a time. No microphone capture or customer text is transmitted. */
export class NotificationVoice {
  private context: AudioContext | null = null;
  private seen = new Set<string>();
  private queue: Notice[] = [];
  private busy = false;
  private disposed = false;
  private cancel: (() => void) | null = null;
  private audio: HTMLAudioElement | null = null;
  constructor(private startSession: StartSession | null) {}

  unlock = () => {
    if (this.disposed || !useSound.getState().preferences.enabled) return;
    try {
      this.context ??= new AudioContext();
      void this.context
        .resume()
        .then(() => {
          if (this.disposed) return;
          useSound.setState({ status: "ready" });
          void this.pump();
        })
        .catch(() => useSound.setState({ status: "locked" }));
    } catch {
      useSound.setState({ status: "unavailable" });
    }
  };

  enqueue(notice: Notice) {
    const p = useSound.getState().preferences;
    if (this.disposed || !p.enabled || p.volume === 0) return;
    if (notice.kind !== "test" && !(notice.kind === "approval" ? p.approvals : p.important)) return;
    if (this.seen.has(notice.key)) return;
    this.seen.add(notice.key);
    const oldest = this.seen.values().next().value;
    if (this.seen.size > 300 && oldest) this.seen.delete(oldest);
    // Prefer approvals, keep the backlog short, and never overlap spoken alerts.
    if (notice.kind === "approval") this.queue.unshift(notice);
    else this.queue.push(notice);
    if (this.queue.length > 4) this.queue.pop();
    void this.pump();
  }

  preferencesChanged() {
    const p = useSound.getState().preferences;
    if (this.audio) this.audio.volume = p.volume;
    if (!p.enabled || p.volume === 0) {
      this.queue = [];
      this.cancel?.();
    }
  }

  private chime() {
    const context = this.context;
    if (!context || context.state !== "running") return;
    const gain = context.createGain();
    gain.gain.setValueAtTime(0, context.currentTime);
    gain.gain.linearRampToValueAtTime(
      useSound.getState().preferences.volume * 0.12,
      context.currentTime + 0.015,
    );
    gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.32);
    gain.connect(context.destination);
    const tone = context.createOscillator();
    tone.frequency.setValueAtTime(740, context.currentTime);
    tone.frequency.setValueAtTime(988, context.currentTime + 0.12);
    tone.connect(gain);
    tone.onended = () => {
      tone.disconnect();
      gain.disconnect();
    };
    tone.start();
    tone.stop(context.currentTime + 0.34);
  }

  private async pump() {
    if (this.busy || this.disposed || !this.queue.length) return;
    if (!this.context || this.context.state !== "running") {
      useSound.setState({ status: "locked" });
      return;
    }
    const notice = this.queue.shift();
    if (!notice) return;
    this.busy = true;
    try {
      const p = useSound.getState().preferences;
      if (p.mode === "chime") {
        this.chime();
        return;
      }
      if (!this.startSession) throw new Error("Live requires a server connection");
      await this.speak(notice);
    } catch (error) {
      if (!this.disposed && useSound.getState().preferences.enabled) {
        if (!(error instanceof CoreError && ["CONFLICT", "NOT_FOUND"].includes(error.code))) {
          this.chime();
          useSound.setState({ status: "unavailable" });
        }
      }
    } finally {
      this.busy = false;
      if (!this.disposed) void this.pump();
    }
  }

  private async speak(notice: Notice) {
    const context = this.context;
    const startSession = this.startSession;
    if (!context || !startSession) throw new Error("Live is unavailable");
    const pc = new RTCPeerConnection();
    const events = pc.createDataChannel("oai-events");
    const abort = new AbortController();
    // Keep the Live clock active with generated silence, never the user's microphone.
    const silence = context.createBufferSource();
    silence.buffer = context.createBuffer(1, context.sampleRate, context.sampleRate);
    silence.loop = true;
    const outgoing = context.createMediaStreamDestination();
    silence.connect(outgoing);
    silence.start();
    outgoing.stream.getTracks().forEach((track) => pc.addTrack(track, outgoing.stream));
    const audio = new Audio();
    this.audio = audio;
    audio.autoplay = true;
    audio.volume = useSound.getState().preferences.volume;
    let analyzer: AnalyserNode | null = null;
    const nodes: AudioNode[] = [];
    let closing = false;
    let heard = false;
    let lastSound = performance.now();
    let announcement = "";
    let ready = false;
    let ended = false;
    let finish!: (error?: Error) => void;
    const done = new Promise<void>((resolve, reject) => {
      finish = (error) => (error ? reject(error) : resolve());
    });
    // A rejected transport before the setup await finishes must not become an unhandled rejection.
    void done.catch(() => undefined);
    const timers: ReturnType<typeof setTimeout>[] = [];
    const close = () => {
      if (closing || ended) return;
      closing = true;
      if (events.readyState === "open") events.send(JSON.stringify({ type: "session.close" }));
      timers.push(setTimeout(() => finish(), 4000));
    };
    this.cancel = () => {
      abort.abort();
      close();
      audio.pause();
    };
    pc.ontrack = (event) => {
      if (ended || closing) return;
      const stream = new MediaStream([event.track]);
      audio.srcObject = stream;
      const incoming = context.createMediaStreamSource(stream);
      analyzer = context.createAnalyser();
      analyzer.fftSize = 256;
      incoming.connect(analyzer);
      nodes.push(incoming, analyzer);
      void audio.play().catch(() => {
        useSound.setState({ status: "locked" });
        finish(new Error("Audio playback blocked"));
      });
    };
    const announce = () => {
      if (!ready || !announcement || closing) return;
      events.send(
        JSON.stringify({
          type: "session.instructions.append",
          event_id: "finora_notice",
          delegation_id: null,
          content: `Immediately say this announcement once in Iraqi Arabic, then stay silent: ${announcement}`,
        }),
      );
      announcement = "";
    };
    events.onmessage = ({ data }) => {
      try {
        const event = JSON.parse(String(data)) as { type?: string };
        if (event.type === "session.started") {
          ready = true;
          announce();
        }
        if (event.type === "session.closed") finish();
        if (event.type === "error") finish(new Error("Live command failed"));
      } catch {
        finish(new Error("Invalid Live event"));
      }
    };
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "failed") finish(new Error("Voice connection failed"));
    };
    events.onclose = () => {
      if (!ended) finish(closing ? undefined : new Error("Voice disconnected"));
    };
    const started = performance.now();
    const monitor = setInterval(() => {
      if (!analyzer || closing) return;
      const samples = new Uint8Array(analyzer.fftSize);
      analyzer.getByteTimeDomainData(samples);
      if (samples.some((value) => Math.abs(value - 128) > 3)) {
        heard = true;
        lastSound = performance.now();
        useSound.setState({ status: "speaking" });
      } else if (heard && performance.now() - lastSound > 2000 && performance.now() - started > 5000) close();
    }, 150);
    timers.push(setTimeout(() => (heard ? close() : finish(new Error("No Live speech received"))), 25000));
    useSound.setState({ status: "connecting" });
    try {
      await pc.setLocalDescription(await pc.createOffer());
      if (pc.iceGatheringState !== "complete") {
        await new Promise<void>((resolve, reject) => {
          const timeout = setTimeout(() => reject(new Error("Voice connection timed out")), 8000);
          timers.push(timeout);
          pc.onicegatheringstatechange = () => {
            if (pc.iceGatheringState === "complete") {
              clearTimeout(timeout);
              resolve();
            }
          };
          abort.signal.addEventListener("abort", () => reject(new Error("Canceled")), { once: true });
        });
      }
      if (abort.signal.aborted || this.disposed) return;
      const sdp = pc.localDescription?.sdp;
      if (!sdp) throw new Error("Missing audio offer");
      const session = await startSession(notice, sdp, abort.signal);
      if (abort.signal.aborted || this.disposed) return;
      announcement = session.announcement;
      await pc.setRemoteDescription({ type: "answer", sdp: session.transport.sdp });
      announce();
      await done;
      if (!heard && !abort.signal.aborted) throw new Error("No speech was played");
      if (!this.disposed) useSound.setState({ status: "ready" });
    } finally {
      ended = true;
      clearInterval(monitor);
      timers.forEach(clearTimeout);
      if (events.readyState === "open" && !closing) events.send(JSON.stringify({ type: "session.close" }));
      audio.pause();
      audio.srcObject = null;
      nodes.forEach((node) => node.disconnect());
      outgoing.stream.getTracks().forEach((track) => track.stop());
      silence.stop();
      silence.disconnect();
      outgoing.disconnect();
      events.close();
      pc.close();
      this.audio = null;
      this.cancel = null;
    }
  }

  dispose() {
    this.disposed = true;
    this.queue = [];
    this.cancel?.();
    if (this.context) void this.context.close();
  }
}
