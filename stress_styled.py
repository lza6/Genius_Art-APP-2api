import concurrent.futures, json, base64, time, urllib.request
BASE='http://127.0.0.1:8907'; HDR={'Content-Type':'application/json','Authorization':'Bearer sk-geniusart-demo'}
img=base64.b64encode(open('ghibli_cat.jpg','rb').read()).decode()
styles=['AM_01_v2','CA_01_v2','HS_01_v2','TT_01_v2']
def gen(i):
    t0=time.time()
    body={'model':'genius-art-styled','prompt':f'portrait scene {i}','style':styles[i%len(styles)],'image':img}
    try:
        r=urllib.request.urlopen(urllib.request.Request(BASE+'/v1/images/generations',
            data=json.dumps(body).encode(), headers=HDR), timeout=400)
        d=json.loads(r.read()); return (i, bool(d.get('data')), round(time.time()-t0,1), '')
    except urllib.error.HTTPError as e: return (i, False, round(time.time()-t0,1), str(e.code))
    except Exception as e: return (i, False, round(time.time()-t0,1), str(e)[:40])
for conc in (4,):
    t0=time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as ex:
        rs=list(ex.map(gen, range(conc)))
    lat=sorted(r[2] for r in rs); ok=sum(1 for r in rs if r[1])
    print(f'styled {conc}并发: ok {ok}/{conc} wall {round(time.time()-t0,1)}s lat={lat} fails={[r[3] for r in rs if not r[1]]}')
