import { spawn } from "node:child_process";
import path from "node:path";
import { once } from "node:events";
import { rmSync } from "node:fs";
import { createServer, request as forwardRequest } from "node:http";

/** Real Flask audit views with a disposable tenant; login alone is a fixture. */
export async function startAuditServer() {
  const root = path.resolve(__dirname, "../../..");
  const child = spawn(
    process.env.FINORA_TEST_PYTHON ?? "C:/Users/msi/AppData/Local/Programs/Python/Python311/python.exe",
    [path.join(root, "tests/_support/smart_audit_server.py")],
    {
      cwd: root,
      windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" },
    },
  );
  let log = "";
  child.stderr.on("data", (data: Buffer) => {
    log = (log + data.toString()).slice(-6000);
  });
  const ready = await new Promise<{ url: string; tenant: string }>((resolve, reject) => {
    let output = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(Error(`Audit server startup timeout: ${log}`));
    }, 90000);
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      reject(Error(`Audit server exited ${code}: ${log}`));
    });
    child.stdout.on("data", (data: Buffer) => {
      output += data.toString();
      const match = /\{"ready": true, "url": "([^"]+)", "tenant": "([^"]+)"\}/.exec(output);
      if (match?.[1] && match[2]) {
        clearTimeout(timer);
        resolve({ url: match[1], tenant: match[2] });
      }
    });
  });
  let online = true;
  const network = createServer((incoming, outgoing) => {
    if (!online) {
      incoming.socket.destroy();
      return;
    }
    const forward = forwardRequest(
      new URL(incoming.url ?? "/", ready.url),
      { method: incoming.method, headers: incoming.headers },
      (response) => {
        outgoing.writeHead(response.statusCode ?? 502, response.headers);
        response.pipe(outgoing);
      },
    );
    forward.on("error", (error) => {
      log = (log + error.message).slice(-6000);
      outgoing.destroy();
    });
    incoming.pipe(forward);
  });
  await new Promise<void>((resolve, reject) => {
    network.once("error", reject);
    network.listen(0, "127.0.0.1", resolve);
  });
  const address = network.address();
  if (!address || typeof address === "string") throw Error("Missing test network port");
  return {
    ...ready,
    url: `http://127.0.0.1:${address.port}`,
    backendUrl: ready.url,
    setOnline(value: boolean) {
      online = value;
    },
    async close() {
      network.closeAllConnections();
      await new Promise<void>((resolve, reject) =>
        network.close((error) => (error ? reject(error) : resolve())),
      );
      if (child.exitCode !== null) return;
      const stopped = once(child, "exit");
      const timer = setTimeout(() => child.kill(), 10000);
      try {
        await fetch(`${ready.url}/__audit_test/shutdown`, {
          method: "POST",
          signal: AbortSignal.timeout(5000),
        });
      } catch (error) {
        log = (log + String(error)).slice(-6000);
        child.kill();
      } finally {
        await stopped;
        clearTimeout(timer);
      }
      const tenantFile = path.resolve(root, "tenants", `${ready.tenant}.db`);
      if (
        !/^test_smart_inventory_audit_\d+_[a-f0-9]{8}$/.test(ready.tenant) ||
        path.dirname(tenantFile) !== path.resolve(root, "tenants")
      )
        throw Error("Unsafe tenant cleanup");
      for (const suffix of ["", "-wal", "-shm"]) rmSync(`${tenantFile}${suffix}`, { force: true });
    },
    log: () => log,
  };
}
