import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { pool } from "../src/lib/db.js";

async function run() {
  const migrationsDir = join(process.cwd(), "migrations");
  const files = (await readdir(migrationsDir))
    .filter((name) => name.endsWith(".sql"))
    .sort((a, b) => a.localeCompare(b));

  if (!files.length) {
    console.log("No migrations found.");
    return;
  }

  for (const file of files) {
    const sql = await readFile(join(migrationsDir, file), "utf8");
    console.log(`Applying migration: ${file}`);
    await pool.query(sql);
  }

  console.log("Migrations completed.");
}

run()
  .catch((error) => {
    console.error("Migration failed:", error?.message ?? error);
    if (String(error?.code ?? "").startsWith("28") || String(error?.message ?? "").includes("password")) {
      console.error("Tip: Check DATABASE_URL in .env (user/password/host must match your PostgreSQL server).");
    }
    process.exit(1);
  })
  .finally(async () => {
    await pool.end();
  });
