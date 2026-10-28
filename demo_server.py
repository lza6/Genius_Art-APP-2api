"""
Genius Art (gen-ai.amobear.com) 2API demo server
- /v1/images/generations  (OpenAI-compatible)
- 加密桥: frida RPC -> 模拟器内 libamg.so
- 号池: device_id 伪造, JWT 14天, 缓存复用
"""
import frida, json, time, threading, queue, os, random, string, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request

WORKDIR = os.path.dirname(os.path.abspath(__file__))
DEVICE_SERIAL = sys.argv[1] if len(sys.argv) > 1 else 'emulator-5554'
APP_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8907
PROXY = 'http://127.0.0.1:10808'
UPSTREAM = 'https://gen-ai.amobear.com'
API_KEY = 'sk-geniusart-demo'

proxy_handler = urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY})
opener = urllib.request.build_opener(proxy_handler)
import ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
import http.client

# ---------- frida bridge ----------
class CryptoBridge:
    def __init__(self, serial):
        self.dev = frida.get_device(serial)
        self.lock = threading.Lock()
        self.script = None
        self._attach()

    def _find_pid(self):
        for a in self.dev.enumerate_applications():
            if a.identifier == 'com.aiart.artgenerator.photoeditor.aiimage':
                return a.pid
        return None

    def _attach(self):
        pid = self._find_pid()
        if not pid:
            print('[bridge] app missing — auto-heal')
            import heal
            heal.SERIAL = self.dev.id
            os.environ['HEAL_SERIAL'] = self.dev.id
            pid = heal.ensure()
        if not pid or pid == '0':
            raise RuntimeError('app not running on ' + self.dev.id)
        self.session = self.dev.attach(pid)
        self.script = self.session.create_script(
            open(os.path.join(WORKDIR, 'rpc_script.js'), encoding='utf-8').read())
        self.script.load()
        print(f'[bridge] attached pid={pid}')

    def call(self, fn, *args):
        with self.lock:
            for attempt in range(3):
                try:
                    return getattr(self.script.exports_sync, fn)(*args)
                except Exception as e:
                    print(f'[bridge] retry {attempt}: {e}')
                    time.sleep(2)
                    try:
                        self._attach()
                    except Exception as e2:
                        print(f'[bridge] reattach fail: {e2}')
                        time.sleep(5)
            raise RuntimeError('crypto bridge down')

bridge = CryptoBridge(DEVICE_SERIAL)

# ---------- token pool ----------
class TokenPool:
    def __init__(self):
        self.tokens = {}          # device_id -> jwt
        self.lock = threading.Lock()

    @staticmethod
    def fake_device_id():
        return ''.join(random.choices('0123456789abcdef', k=16))

    def get(self, device_id=None):
        did = device_id or self.fake_device_id()
        with self.lock:
            if did in self.tokens:
                return self.tokens[did]
        # 1) build encrypted get-token body
        enc = bridge.call('gettoken', 'TokenFirbaseTest')
        body = json.dumps({'data': enc}).encode()
        # 2) POST
        conn = http.client.HTTPSConnection('gen-ai.amobear.com', timeout=30, context=ctx)
        conn.set_tunnel('gen-ai.amobear.com', 443) if False else None
        # use opener for proxy
        req = urllib.request.Request(UPSTREAM + '/v5/account/get-token', data=body,
                                     headers={'Content-Type': 'application/json'})
        resp = opener.open(req, timeout=30)
        cipher = resp.read().decode().strip().strip('"')
        # 3) decrypt
        dec = bridge.call('decrypt', cipher)
        jwt = json.loads(dec)['token']
        with self.lock:
            self.tokens[did] = jwt
        print(f'[pool] new token device={did[:8]}.. total={len(self.tokens)}')
        return jwt

pool = TokenPool()

# ---------- upstream t2i ----------
def generate(prompt, tier='1'):
    jwt = pool.get()
    inner = json.dumps({'type': '1', 'tier': tier, 'prompt': prompt})
    enc = bridge.call('encrypt', inner, 'TokenFirbaseTest')
    body = json.dumps({'data': enc}).encode()
    req = urllib.request.Request(UPSTREAM + '/v5/tools/prompt-to-image', data=body,
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + jwt})
    resp = opener.open(req, timeout=120)
    cipher = resp.read().decode().strip().strip('"')
    dec = bridge.call('decrypt', cipher)
    return json.loads(dec)

# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print('[http]', fmt % args)

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/health':
            return self._json(200, {'status': 'ok', 'pool': len(pool.tokens),
                                    'device': DEVICE_SERIAL})
        self._json(404, {'error': 'not found'})

    def do_POST(self):
        if self.path != '/v1/images/generations':
            return self._json(404, {'error': 'not found'})
        if self.headers.get('Authorization', '') != 'Bearer ' + API_KEY:
            return self._json(401, {'error': 'bad api key'})
        try:
            length = int(self.headers.get('Content-Length', 0))
            req = json.loads(self.rfile.read(length))
            prompt = req.get('prompt') or (req.get('input') if isinstance(req.get('input'), str) else None)
            if not prompt:
                return self._json(400, {'error': 'prompt required'})
            tier = str(req.get('tier', '1'))
            n = min(int(req.get('n', 1)), 4)
            results = []
            for _ in range(n):
                t0 = time.time()
                out = generate(prompt, tier)
                dt = time.time() - t0
                url = out.get('result', {}).get('url')
                print(f'[t2i] {dt:.1f}s prompt={prompt[:40]!r} ok={bool(url)}')
                if url:
                    results.append({'url': url})
                else:
                    return self._json(502, {'error': out})
            return self._json(200, {
                'created': int(time.time()),
                'data': results
            })
        except urllib.error.HTTPError as e:
            return self._json(e.code, {'error': f'upstream {e.code}: {e.read()[:200]}'})
        except Exception as e:
            return self._json(500, {'error': str(e)})

if __name__ == '__main__':
    # warmup
    print('[warmup] fetching first token...')
    pool.get()
    print(f'[ready] http://127.0.0.1:{APP_PORT}/v1/images/generations  key={API_KEY}')
    HTTPServer(('127.0.0.1', APP_PORT), Handler).serve_forever()
