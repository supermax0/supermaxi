"""Concurrent-shopper load test for the storefront (Smart Commerce V2, Sprint 10) — NOT part of the pytest run.

Starts the real app under waitress — ``--workers`` separate processes, the way production runs several gunicorn
workers (one Python process can use only one core at a time) — with a throw-away store, then for each level
(default 100, 500, 1000 virtual shoppers) runs shoppers that browse like people do — home → search → suggestions →
product — with 1–3 s of thinking between pages, spread over the workers. Reports per-request latency
(p50/p95/p99), errors, throughput and the servers' CPU / memory. Client and servers share this machine, so the
numbers are a lower bound for a real server.

    python tests/perf/load_storefront.py --workers 4 --levels 100,500,1000 --seconds 30 --out docs/perf/load.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
QUERIES = ["شاشة 55 سمارت", "سبلت طن ونص انفرتر", "غسالة حوضين", "ثلاجة نوفروست", "الجي خمسين", "طباخ غاز",
           "شاشة سامسونج 65 بأقل من مليون", "سبلت كري 2 طن"]


def pct(values, p):
    from modules.store_analytics.perf import percentile

    return round(percentile(values, p), 1) if values else None


def free_port() -> int:
    # never share a port with another local server (Windows lets two processes listen on one)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def shopper(session, base, deadline, product_ids, out, rnd, think=(1.0, 3.0)):
    while time.monotonic() < deadline:
        q = rnd.choice(QUERIES)
        for kind, url in (("home", f"{base}/"), ("search", f"{base}/?q={quote(q)}"),
                          ("suggest", f"{base}/api/products?per_page=6&q={quote(q[:6])}"),
                          ("product", f"{base}/product/{rnd.choice(product_ids)}")):
            if time.monotonic() >= deadline:
                return
            started = time.perf_counter()
            try:
                async with session.get(url) as res:
                    await res.read()
                    ok = res.status == 200
            except Exception:
                ok = False
            out.append((kind, (time.perf_counter() - started) * 1000, ok))
            await asyncio.sleep(rnd.uniform(*think))


async def level(bases, users, seconds, product_ids, pids, gpc=False, think=(1.0, 3.0)):
    import aiohttp
    import psutil

    procs = [psutil.Process(p) for p in pids]
    samples, out = [], []
    deadline = time.monotonic() + seconds
    stop = asyncio.Event()

    async def sample():
        for p in procs:
            p.cpu_percent(None)
        while not stop.is_set():
            await asyncio.sleep(1)
            try:
                samples.append((sum(p.cpu_percent(None) for p in procs), sum(p.memory_info().rss for p in procs) / 2**20))
            except Exception:
                pass

    connector = aiohttp.TCPConnector(limit=users)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60), connector=connector,
                                     cookie_jar=aiohttp.DummyCookieJar(),
                                     headers={"Sec-GPC": "1"} if gpc else None) as session:
        sampler = asyncio.create_task(sample())
        started = time.monotonic()
        await asyncio.gather(*(shopper(session, bases[i % len(bases)], deadline, product_ids, out, random.Random(i), think)
                               for i in range(users)))
        elapsed = time.monotonic() - started
        stop.set()
        await sampler
    by_kind = {}
    for kind in ("home", "search", "suggest", "product"):
        ms = [m for k, m, ok in out if k == kind and ok]
        by_kind[kind] = {"count": len(ms), "p50_ms": pct(ms, 50), "p95_ms": pct(ms, 95), "p99_ms": pct(ms, 99)}
    errors = sum(1 for _, _, ok in out if not ok)
    return {"users": users, "seconds": round(elapsed, 1), "requests": len(out), "errors": errors,
            "error_rate_pct": round(100 * errors / len(out), 2) if out else None,
            "throughput_rps": round(len(out) / elapsed, 1) if elapsed else None, "by_page": by_kind,
            "servers_cpu_pct_avg": round(sum(c for c, _ in samples) / len(samples), 1) if samples else None,
            "servers_cpu_pct_max": round(max((c for c, _ in samples), default=0), 1),
            "servers_rss_mb_max": round(max((m for _, m in samples), default=0))}


def start(args, tenant, port, seed):
    cmd = [sys.executable, str(Path(__file__).with_name("_serve.py")), "--port", str(port), "--tenant", tenant,
           "--products", str(args.products), "--threads", str(args.threads)]
    if not seed:
        cmd.append("--no-seed")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                            errors="replace")
    while True:
        line = proc.stdout.readline()
        if not line:
            raise SystemExit("server did not start")
        if "READY" in line:
            # keep draining its output: a full pipe would block the server on its next log line
            import threading

            threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()
            return proc


def main():
    import urllib.request

    import psutil

    parser = argparse.ArgumentParser()
    parser.add_argument("--levels", default="100,500,1000")
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--products", type=int, default=3000)
    parser.add_argument("--threads", type=int, default=16)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--think", default="1,3", help="seconds a shopper waits between pages: min,max")
    parser.add_argument("--gpc", action="store_true", help="shoppers send Sec-GPC: 1 (no personalisation / events)")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    tenant = f"perf_load_{os.getpid()}"
    servers = []
    result = {"products": args.products, "workers": args.workers, "think_seconds": args.think, "threads_per_worker": args.threads,
              "machine": {"cpu": os.cpu_count(), "ram_gb": round(psutil.virtual_memory().total / 2**30, 1)}, "levels": []}
    try:
        ports = [free_port() for _ in range(args.workers)]
        servers.append(start(args, tenant, ports[0], seed=True))
        servers += [start(args, tenant, p, seed=False) for p in ports[1:]]
        bases = [f"http://127.0.0.1:{p}/shop/{tenant}" for p in ports]
        for base in bases:  # first request per worker builds its caches — not part of the measurement
            urllib.request.urlopen(f"{base}/", timeout=120).read()
            urllib.request.urlopen(f"{base}/?q={quote(QUERIES[0])}", timeout=120).read()
        sitemap = urllib.request.urlopen(f"{bases[0]}/sitemap-products-1.xml", timeout=60).read().decode("utf-8")
        ids = [int(part.split("<")[0]) for part in sitemap.split("/product/")[1:]]
        for users in [int(x) for x in args.levels.split(",") if x.strip()]:
            res = asyncio.run(level(bases, users, args.seconds, ids[:2000], [s.pid for s in servers], args.gpc,
                                    tuple(float(x) for x in args.think.split(","))))
            print(json.dumps(res, ensure_ascii=False), flush=True)
            result["levels"].append(res)
    finally:
        for server in servers:
            server.kill()
            server.wait(timeout=30)
        time.sleep(1)
        for suffix in ("", "-wal", "-shm"):
            try:
                (ROOT / "tenants" / f"{tenant}.db{suffix}").unlink(missing_ok=True)
            except OSError as exc:
                print("cleanup:", exc, file=sys.stderr)
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    main()
