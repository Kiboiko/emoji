"""Isolated stage only: 300 users, active promotion included, no concurrent builds/tests."""
import asyncio
import json
import os
import random
import time
from pathlib import Path
import httpx
from growth_http import signed  # also verifies isolated environment


async def main():
    base = os.environ["BASE"]
    users = int(os.environ.get("LOAD_USERS_REAL", "300"))
    seconds = int(os.environ.get("LOAD_SECONDS", "50"))
    async with httpx.AsyncClient(base_url=base, timeout=30) as c:
        headers = []
        for i in range(20):
            r = await c.post("/api/auth/telegram", headers=signed(6_900_000_000+i))
            r.raise_for_status();headers.append({"Authorization":"Bearer "+r.json()["access_token"]})
        categories = [r["id"] for r in (await c.get("/api/categories")).json()]
        products = [r["id"] for r in (await c.get("/api/products?limit=100")).json()]
    lat, errors = {}, 0
    start = time.monotonic()
    async with httpx.AsyncClient(base_url=base, timeout=30, limits=httpx.Limits(max_connections=users+20,max_keepalive_connections=users+20)) as c:
        async def user(index):
            nonlocal errors
            rng = random.Random(index);await asyncio.sleep(rng.random()*5)
            while time.monotonic()-start < seconds:
                roll=rng.random()
                if roll<.38:name,path="catalog",f"/api/products?skip={rng.randrange(0,4900,40)}&limit=40&lang=ru"
                elif roll<.50:name,path="category","/api/products?category_id="+rng.choice(categories)
                elif roll<.58:name,path="search",f"/api/products?search=Нагрузка%20{rng.randrange(1,5000)}"
                elif roll<.68:name,path="product","/api/products/"+rng.choice(products)
                elif roll<.74:name,path="categories","/api/categories"
                elif roll<.80:name,path="stores","/api/stores"
                elif roll<.90:name,path="cart","/api/cart"
                elif roll<.95:name,path="rankings","/api/market-rankings/current"
                else:name,path="giveaways","/api/giveaways"
                tick=time.perf_counter()
                try:r=await c.get(path,headers=headers[index%20]);errors+=r.status_code!=200
                except httpx.HTTPError:errors+=1
                lat.setdefault(name,[]).append((time.perf_counter()-tick)*1000)
                await asyncio.sleep(rng.uniform(1.5,5))
        await asyncio.gather(*(user(i) for i in range(users)))
    def pct(data,p):return round(sorted(data)[min(len(data)-1,int(len(data)*p))],1)
    all_ms=[v for values in lat.values() for v in values]
    result={"users":users,"seconds":round(time.monotonic()-start,1),"requests":len(all_ms),"errors":errors,
        "p95_ms":pct(all_ms,.95),"p99_ms":pct(all_ms,.99),"by_endpoint":{k:{"n":len(v),"p95_ms":pct(v,.95)} for k,v in lat.items()}}
    Path("/outbox/project-load.json").write_text(json.dumps(result),encoding="utf-8")
    print(json.dumps(result),flush=True)
    return errors!=0 or result["p95_ms"]>=300 or result["p99_ms"]>=1000


if __name__=="__main__":raise SystemExit(asyncio.run(main()))
