/** SQLite stays in main. Each acknowledged mutation has an encrypted, atomic disk checkpoint. */
import { createCipheriv, createDecipheriv, randomBytes, randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import initSqlJs, { type Database, type SqlJsStatic, type SqlValue } from "sql.js";
import { setTimeout as delay } from "node:timers/promises";

const MAGIC = Buffer.from("FINORA-OFFLINE-1\n");
export function encryptDatabase(data: Uint8Array, key: Buffer): Buffer {
  const nonce = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, nonce);
  cipher.setAAD(MAGIC);
  const ciphertext = Buffer.concat([cipher.update(data), cipher.final()]);
  return Buffer.concat([MAGIC, nonce, cipher.getAuthTag(), ciphertext]);
}
export function decryptDatabase(data: Buffer, key: Buffer): Uint8Array {
  if (!data.subarray(0, MAGIC.length).equals(MAGIC))
    throw new Error("ملف الأوفلاين غير صالح؛ لم تُحذف البيانات.");
  const offset = MAGIC.length;
  const cipher = createDecipheriv("aes-256-gcm", key, data.subarray(offset, offset + 12));
  cipher.setAAD(MAGIC);
  cipher.setAuthTag(data.subarray(offset + 12, offset + 28));
  return Buffer.concat([cipher.update(data.subarray(offset + 28)), cipher.final()]);
}

export async function atomicWrite(file: string, data: Uint8Array): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const temporary = `${file}.${randomUUID()}.tmp`;
  let renamed = false;
  try {
    const handle = await fs.open(temporary, "wx", 0o600);
    try {
      await handle.writeFile(data);
      await handle.sync();
    } finally {
      await handle.close();
    }
    await replaceFile(temporary, file);
    renamed = true;
  } finally {
    if (!renamed)
      await fs.unlink(temporary).catch((error: NodeJS.ErrnoException) => {
        if (error.code !== "ENOENT") throw error;
      });
  }
}

/** Windows scanners can hold the destination briefly. Never remove the old checkpoint. */
export async function replaceFile(
  temporary: string,
  file: string,
  rename: typeof fs.rename = fs.rename,
  pause: (ms: number) => Promise<unknown> = delay,
): Promise<void> {
  for (let attempt = 0; ; attempt++) {
    try {
      await rename(temporary, file);
      return;
    } catch (error) {
      if (attempt >= 6 || !["EPERM", "EBUSY", "EACCES"].includes((error as NodeJS.ErrnoException).code ?? ""))
        throw error;
      await pause(Math.min(40 * 2 ** attempt, 640));
    }
  }
}

export class OfflineDatabase {
  private tail: Promise<unknown> = Promise.resolve();
  private constructor(
    private db: Database,
    private SQL: SqlJsStatic,
    private file: string,
    private key: Buffer,
  ) {}

  static async open(file: string, key: Buffer, wasmFile: string): Promise<OfflineDatabase> {
    const SQL = await initSqlJs({ locateFile: () => wasmFile });
    let bytes: Uint8Array | undefined;
    try {
      bytes = decryptDatabase(await fs.readFile(file), key);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    const db = new SQL.Database(bytes);
    db.run(`CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS contexts (id TEXT PRIMARY KEY, session TEXT NOT NULL, verified INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS responses (scope TEXT NOT NULL, key TEXT NOT NULL, body TEXT NOT NULL, saved INTEGER NOT NULL, PRIMARY KEY(scope,key));
      CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, scope TEXT NOT NULL, payload TEXT NOT NULL,
        label TEXT NOT NULL, total INTEGER NOT NULL, created INTEGER NOT NULL,
        status TEXT NOT NULL, error TEXT, invoice TEXT);
      CREATE INDEX IF NOT EXISTS operations_scope ON operations(scope,created);`);
    db.run(`CREATE TABLE IF NOT EXISTS snapshots (scope TEXT NOT NULL, id TEXT NOT NULL, manifest TEXT, state TEXT NOT NULL, error TEXT, stale INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(scope,id));
      CREATE TABLE IF NOT EXISTS snapshot_records (scope TEXT NOT NULL, generation TEXT NOT NULL, dataset TEXT NOT NULL, position INTEGER NOT NULL, record_id INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(scope,generation,dataset,position));
      CREATE INDEX IF NOT EXISTS snapshot_records_id ON snapshot_records(scope,generation,dataset,record_id);`);
    db.run(`CREATE TABLE IF NOT EXISTS stock_requests(id TEXT PRIMARY KEY,scope TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL,error TEXT);
      CREATE TABLE IF NOT EXISTS device_stock(id TEXT PRIMARY KEY,scope TEXT NOT NULL,grant_id TEXT NOT NULL,product_id INTEGER NOT NULL,name TEXT NOT NULL,color TEXT NOT NULL,quantity INTEGER NOT NULL,used INTEGER NOT NULL DEFAULT 0,returned INTEGER NOT NULL DEFAULT 0,frozen INTEGER NOT NULL DEFAULT 0);
      CREATE INDEX IF NOT EXISTS device_stock_scope ON device_stock(scope,product_id,color);
      CREATE TABLE IF NOT EXISTS operation_reservations(operation_id TEXT PRIMARY KEY,parts TEXT NOT NULL,receipt TEXT NOT NULL);`);
    db.run(
      "CREATE TABLE IF NOT EXISTS hr_snapshots(scope TEXT PRIMARY KEY,body TEXT NOT NULL,saved INTEGER NOT NULL,stale INTEGER NOT NULL DEFAULT 0)",
    );
    db.run(`CREATE TABLE IF NOT EXISTS customer_commands(scope TEXT NOT NULL,key TEXT NOT NULL,path TEXT NOT NULL,target TEXT NOT NULL,
      payload TEXT NOT NULL,fingerprint TEXT NOT NULL,created INTEGER NOT NULL,state TEXT NOT NULL,PRIMARY KEY(scope,key));
      CREATE INDEX IF NOT EXISTS customer_commands_target ON customer_commands(scope,target);`);
    db.run(`CREATE TABLE IF NOT EXISTS audit_records(scope TEXT NOT NULL,session_id INTEGER NOT NULL,line_id INTEGER NOT NULL,
      body TEXT NOT NULL,ticket TEXT NOT NULL,version INTEGER NOT NULL,issued TEXT NOT NULL,permissions TEXT NOT NULL,
      PRIMARY KEY(scope,session_id,line_id));
      CREATE TABLE IF NOT EXISTS audit_sessions(scope TEXT NOT NULL,id INTEGER NOT NULL,body TEXT NOT NULL,permissions TEXT NOT NULL,PRIMARY KEY(scope,id));
      CREATE TABLE IF NOT EXISTS audit_commands(scope TEXT NOT NULL,key TEXT NOT NULL,path TEXT NOT NULL,target TEXT NOT NULL,
      session_id INTEGER,line_id INTEGER,action TEXT NOT NULL,payload TEXT NOT NULL,fingerprint TEXT NOT NULL,created INTEGER NOT NULL,
      state TEXT NOT NULL,error TEXT,reply TEXT,PRIMARY KEY(scope,key));
      CREATE INDEX IF NOT EXISTS audit_commands_target ON audit_commands(scope,target);
      CREATE TABLE IF NOT EXISTS audit_local_history(id INTEGER PRIMARY KEY AUTOINCREMENT,scope TEXT NOT NULL,session_id INTEGER NOT NULL,
      line_id INTEGER,action TEXT NOT NULL,created INTEGER NOT NULL,detail TEXT NOT NULL);`);
    const store = new OfflineDatabase(db, SQL, file, key);
    if (!store.one("SELECT value FROM metadata WHERE key='device'")) {
      await store.write(() => db.run("INSERT INTO metadata VALUES ('device', ?)", [randomUUID()]));
    }
    return store;
  }

  one(sql: string, parameters: SqlValue[] = []): Record<string, SqlValue> | undefined {
    return this.all(sql, parameters)[0];
  }
  all(sql: string, parameters: SqlValue[] = []): Array<Record<string, SqlValue>> {
    const statement = this.db.prepare(sql);
    try {
      statement.bind(parameters);
      const rows: Array<Record<string, SqlValue>> = [];
      while (statement.step()) rows.push(statement.getAsObject());
      return rows;
    } finally {
      statement.free();
    }
  }
  run(sql: string, parameters: SqlValue[] = []): void {
    this.db.run(sql, parameters);
  }
  async write<T>(action: () => T): Promise<T> {
    const task = this.tail.then(async () => {
      const previous = this.db.export();
      try {
        this.db.run("BEGIN IMMEDIATE");
        const result = action();
        this.db.run("COMMIT");
        await atomicWrite(this.file, encryptDatabase(this.db.export(), this.key));
        return result;
      } catch (error) {
        this.db.close();
        this.db = new this.SQL.Database(previous);
        throw error;
      }
    });
    this.tail = task.catch(() => undefined);
    return task;
  }
  async close(): Promise<void> {
    await this.tail;
    this.db.close();
  }
  async settled(): Promise<void> {
    await this.tail;
  }
}
