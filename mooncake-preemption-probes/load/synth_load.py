#!/usr/bin/env python3
"""Synthetic high-concurrency load.

Goal: maximise the number of *running* requests (so the single per-rank store
thread's FIFO backs up) while keeping the KV pool saturated (so preemption
fires constantly). Prompts are random gibberish so nothing dedups in the
store and every save is a real batch_put.
"""
import argparse
import asyncio
import random
import string
import time

import aiohttp


def rand_prompt(n_words: int, rng: random.Random) -> str:
    return " ".join(
        "".join(rng.choices(string.ascii_lowercase, k=rng.randint(3, 9)))
        for _ in range(n_words)
    )


async def one(http, url, model, sem, seed, max_tok, words, res):
    rng = random.Random(seed)
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": rand_prompt(words, rng)
                + "\n\nIgnore the noise above. Write a long, detailed essay.",
            }
        ],
        "max_tokens": max_tok,
        "temperature": 1.0,
        "stream": True,
    }
    async with sem:
        t0 = time.perf_counter()
        ttft = None
        ntok = 0
        try:
            async with http.post(url, json=body) as r:
                if r.status != 200:
                    res.append(("http", r.status, 0, 0.0))
                    return
                async for line in r.content:
                    if line.startswith(b"data: "):
                        if ttft is None:
                            ttft = time.perf_counter() - t0
                        ntok += 1
        except Exception as e:  # noqa: BLE001
            res.append(("exc", str(e)[:60], ntok, time.perf_counter() - t0))
            return
    res.append(("ok", ntok, ntok, ttft or 0.0))


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--model", default="qwen3-32b")
    p.add_argument("--n", type=int, default=600)
    p.add_argument("--concurrency", type=int, default=128)
    p.add_argument("--max-tokens", type=int, default=1024)
    p.add_argument("--words", type=int, default=600)
    a = p.parse_args()

    url = a.base + "/v1/chat/completions"
    sem = asyncio.Semaphore(a.concurrency)
    res: list = []
    t0 = time.perf_counter()
    conn = aiohttp.TCPConnector(limit=a.concurrency + 16)
    async with aiohttp.ClientSession(
        connector=conn, timeout=aiohttp.ClientTimeout(total=7200)
    ) as http:
        await asyncio.gather(
            *[
                one(http, url, a.model, sem, i, a.max_tokens, a.words, res)
                for i in range(a.n)
            ]
        )
    wall = time.perf_counter() - t0

    ok = [r for r in res if r[0] == "ok"]
    bad = [r for r in res if r[0] != "ok"]
    toks = sorted(r[2] for r in ok)
    ttfts = sorted(r[3] for r in ok)
    print(f"\n=== {len(ok)} ok, {len(bad)} bad, wall {wall:.1f}s")
    if ok:
        print(f"out tok total={sum(toks)} median={toks[len(toks) // 2]}")
        print(
            f"TTFT p50={ttfts[len(ttfts) // 2]:.2f}s "
            f"p90={ttfts[int(len(ttfts) * 0.9)]:.2f}s max={ttfts[-1]:.2f}s"
        )
    for r in bad[:5]:
        print("BAD", r)


asyncio.run(main())
