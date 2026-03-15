import { buildApp } from "./app.js";
import { env } from "./config/env.js";
import { pool } from "./lib/db.js";

async function bootstrap() {
  const app = buildApp();

  app.addHook("onClose", async () => {
    await pool.end();
  });

  try {
    await app.listen({ host: env.HOST, port: env.PORT });
    app.log.info(`AI Automation backend listening on http://${env.HOST}:${env.PORT}`);
  } catch (error) {
    app.log.error(error);
    process.exit(1);
  }
}

void bootstrap();
