import { createCipheriv, createDecipheriv, randomBytes, scrypt as derive } from "node:crypto";
import { promisify } from "node:util";
const scrypt = promisify(derive);
const MAGIC = Buffer.from("FINORA-BACKUP-1\n");
export const BACKUP_LIMIT = 256 * 1024 * 1024;
export async function sealBackup(data: Buffer, password: string) {
  if (password.length < 12 || password.length > 256)
    throw Error("كلمة حماية النسخة يجب أن تكون بين 12 و256 حرفاً");
  if (data.length > BACKUP_LIMIT) throw Error("حجم النسخة أكبر من الحد المسموح");
  const salt = randomBytes(16),
    nonce = randomBytes(12);
  const key = (await scrypt(password, salt, 32)) as Buffer;
  try {
    const cipher = createCipheriv("aes-256-gcm", key, nonce);
    cipher.setAAD(MAGIC);
    const encrypted = Buffer.concat([cipher.update(data), cipher.final()]);
    return Buffer.concat([MAGIC, salt, nonce, cipher.getAuthTag(), encrypted]);
  } finally {
    key.fill(0);
  }
}
export async function openBackup(data: Buffer, password: string) {
  if (
    password.length < 12 ||
    password.length > 256 ||
    data.length > BACKUP_LIMIT + 64 ||
    data.length < MAGIC.length + 44 ||
    !data.subarray(0, MAGIC.length).equals(MAGIC)
  )
    throw Error("ملف النسخة أو كلمة الحماية غير صالحين");
  const at = MAGIC.length,
    key = (await scrypt(password, data.subarray(at, at + 16), 32)) as Buffer;
  try {
    const decipher = createDecipheriv("aes-256-gcm", key, data.subarray(at + 16, at + 28));
    decipher.setAAD(MAGIC);
    decipher.setAuthTag(data.subarray(at + 28, at + 44));
    return Buffer.concat([decipher.update(data.subarray(at + 44)), decipher.final()]);
  } catch {
    throw Error("كلمة الحماية غير صحيحة أو النسخة تالفة؛ لم تُستبدل بياناتك");
  } finally {
    key.fill(0);
  }
}
