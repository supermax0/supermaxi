import { playSound, unlockSounds } from "@/services/sounds";

export function scanBeep(ok = true): void {
  unlockSounds();
  playSound(ok ? "scan" : "error");
}
