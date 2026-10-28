"""
Замер производительности по одному маршруту: сколько запросов в секунду выдерживает
бэкенд и какая при этом задержка. Запускать внутри сети стенда.

python bench.py <base> <concurrency> <seconds> <path> [<path> ...]
"""
import asyncio
import sys
import time

import httpx

base, conc, seconds = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
paths = sys.argv[4:]


async def run(path):
    lat, errors = [], 0
    stop = time.time() + seconds
    limits = httpx.Limits(max_connections=conc + 5, max_keepalive_connections=conc + 5)
    async with httpx.AsyncClient(base_url=base, timeout=30, limits=limits) as c:
        async def worker():
            nonlocal errors
            while time.time() < stop:
                t = time.perf_counter()
                try:
                    r = await c.get(path)
                    if r.status_code >= 400:
                        errors += 1
                except Exception:
                    errors += 1
                lat.append((time.perf_counter() - t) * 1000)
        t0 = time.time()
        await asyncio.gather(*(worker() for _ in range(conc)))
        took = time.time() - t0
    lat.sort()
    n = len(lat)
    print(f"{path:<44} c={conc:<3} {n / took:7.0f} rps  p50={lat[n // 2]:6.0f}ms  p95={lat[int(n * .95)]:6.0f}ms  errors={errors}", flush=True)


async def main():
    for p in paths:
        await run(p)


asyncio.run(main())
