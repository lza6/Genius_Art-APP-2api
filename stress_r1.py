"""R1 stress: concurrency + token pool + error handling against demo server."""
import concurrent.futures, json, time, urllib.request, sys

BASE = 'http://127.0.0.1:8907'
KEY = 'sk-geniusart-demo'
HDR = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + KEY}

def gen(i, prompt):
    t0 = time.time()
    try:
        req = urllib.request.Request(BASE + '/v1/images/generations',
            data=json.dumps({'prompt': prompt, 'n': 1, 'tier': '1'}).encode(), headers=HDR)
        r = urllib.request.urlopen(req, timeout=180)
        d = json.loads(r.read())
        ok = 'data' in d and d['data'] and d['data'][0].get('url')
        return (i, ok, round(time.time()-t0, 1), d['data'][0]['url'][:60] if ok else json.dumps(d)[:120])
    except Exception as e:
        return (i, False, round(time.time()-t0, 1), str(e)[:120])

prompts = [
    "a dragon flying over tokyo, neon",
    "portrait of a robot samurai",
    "sunset over mountains, oil painting",
    "cute corgi in a spacesuit",
    "ancient library with floating candles",
    "steampunk airship in storm",
    "koi pond at night, moonlight",
    "wizard cat casting spell",
]
print('== R1: 8 sequential-ish unique prompts (pool growth)')
results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
    futs = [ex.submit(gen, i, p) for i, p in enumerate(prompts)]
    for f in concurrent.futures.as_completed(futs):
        r = f.result()
        results.append(r)
        print(f'  #{r[0]} ok={r[1]} {r[2]}s {r[3]}')

okc = sum(1 for r in results if r[1])
lat = sorted(r[2] for r in results)
print(f'== SUMMARY: {okc}/{len(results)} ok, latency p50={lat[len(lat)//2]}s max={lat[-1]}s')
h = json.loads(urllib.request.urlopen(BASE + '/health', timeout=5).read())
print('pool size:', h['pool'])
