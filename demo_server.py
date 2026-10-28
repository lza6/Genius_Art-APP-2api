"""
Genius Art (gen-ai.amobear.com) 2API demo server
- /v1/models                     模型清单
- /v1/images/generations         OpenAI 兼容（文生图 / 图生风格图）
- /v1/images/edits               OpenAI 兼容 multipart（图生风格图）
- /styles                        1553 个风格模板清单
- 加密桥: frida RPC -> 模拟器内 libamg.so
- 号池: get-token 每次随机 device_id, JWT 14 天, 缓存复用

模型:
  genius-art         文生图   POST /v5/tools/prompt-to-image   512x512  同步
  genius-art-styled  图生风格  POST /v5/tools/predict-art      1152x1536 异步(create→upload→status)
"""
import frida, json, time, threading, os, random, string, sys, ssl, uuid, base64, re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import urllib.request, urllib.error

WORKDIR = os.path.dirname(os.path.abspath(__file__))
DEVICE_SERIAL = sys.argv[1] if len(sys.argv) > 1 else 'emulator-5570'
APP_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8907
PROXY = os.environ.get('GENIUS_PROXY', 'http://127.0.0.1:10808')
UPSTREAM = 'https://gen-ai.amobear.com'
API_KEY = os.environ.get('GENIUS_API_KEY', 'sk-geniusart-demo')
ENCRYPT_KEY = 'TokenFirbaseTest'

_opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY}),
    urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))

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
        self.session = self.dev.attach(int(pid))
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
        self.tokens = {}
        self.lock = threading.Lock()

    @staticmethod
    def fake_device_id():
        return ''.join(random.choices('0123456789abcdef', k=16))

    def get(self, device_id=None):
        did = device_id or self.fake_device_id()
        with self.lock:
            if did in self.tokens:
                return self.tokens[did]
        enc = bridge.call('gettoken', ENCRYPT_KEY)
        req = urllib.request.Request(UPSTREAM + '/v5/account/get-token',
                                     data=json.dumps({'data': enc}).encode(),
                                     headers={'Content-Type': 'application/json'})
        cipher = _opener.open(req, timeout=30).read().decode().strip().strip('"')
        jwt = json.loads(bridge.call('decrypt', cipher))['token']
        with self.lock:
            self.tokens[did] = jwt
        print(f'[pool] new token device={did[:8]}.. total={len(self.tokens)}')
        return jwt

pool = TokenPool()

# ---------- upstream helpers ----------
def _api(path, inner, jwt, timeout=180):
    """POST an encrypted body, return (status, decrypted-dict-or-str)."""
    enc = bridge.call('encrypt', json.dumps(inner), ENCRYPT_KEY)
    req = urllib.request.Request(UPSTREAM + path,
                                 data=json.dumps({'data': enc}).encode(),
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + jwt})
    try:
        r = _opener.open(req, timeout=timeout)
        status, raw = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read().decode()
    cipher = raw.strip().strip('"')
    try:
        dec = bridge.call('decrypt', cipher)
    except Exception:
        dec = None
    if not dec:
        return status, raw[:200]
    try:
        return status, json.loads(dec)
    except Exception:
        return status, dec

def generate(prompt, tier='1'):
    """文生图（prompt-to-image, 同步 512x512）"""
    jwt = pool.get()
    status, out = _api('/v5/tools/prompt-to-image',
                       {'type': '1', 'tier': str(tier), 'prompt': prompt}, jwt, timeout=150)
    if status not in (200, 201) or not isinstance(out, dict):
        raise UpstreamError(status, out)
    url = (out.get('result') or {}).get('url')
    if not url:
        raise UpstreamError(status, out)
    return [url]

def generate_styled(prompt, style, skin_color=0, num_image=1, image_bytes=None,
                    tier='1', poll_timeout=240):
    """图生风格（predict-art, 异步: create -> PUT 参考图 -> status=1 触发/轮询, 1152x1536）"""
    if image_bytes is None:
        raise ValueError('genius-art-styled requires an input image')
    jwt = pool.get()
    fname = uuid.uuid4().hex + '.jpg'
    body = {'type': '1', 'tier': str(tier), 'prompt': prompt or '', 'style': style,
            'skin_color': int(skin_color), 'num_image': str(num_image),
            'original_name': [fname]}
    status, out = _api('/v5/tools/predict-art', body, jwt, timeout=90)
    if status not in (200, 201) or not isinstance(out, dict):
        raise UpstreamError(status, out)
    job_id = out.get('_id')
    links = out.get('link_upload') or []
    if not job_id or not links:
        raise UpstreamError(status, {'error': 'no job/link returned', 'raw': out})

    # GCS V2 signed URL 签名包含 Content-Type=application/octet-stream，必须用它
    put = urllib.request.Request(links[0], data=image_bytes, method='PUT',
                                 headers={'Content-Type': 'application/octet-stream',
                                          'Content-Length': str(len(image_bytes))})
    try:
        pr = _opener.open(put, timeout=120)
        if pr.status not in (200, 201):
            raise UpstreamError(pr.status, 'upload failed')
    except urllib.error.HTTPError as e:
        raise UpstreamError(e.code, f'upload failed: {e.read()[:150]}')

    # 触发 + 轮询（首次通常直接返回结果）
    deadline = time.time() + poll_timeout
    last = None
    while time.time() < deadline:
        st, res = _api('/v5/tools/predict-art/upload-image-status',
                       {'_id': job_id, 'status': 1}, jwt, timeout=180)
        last = res
        if isinstance(res, dict):
            r = res.get('result') or {}
            urls = [u for u in (r.get('arr_url') or []) if u]
            if r.get('url'):
                urls.append(r['url'])
            if urls:
                return urls
        if st in (400, 404) and isinstance(res, dict) and res.get('message') \
                and 'cannot get image_original' in str(res.get('message')):
            raise UpstreamError(st, res)
        time.sleep(4)
    raise UpstreamError(504, {'error': 'job timeout', 'last': last, 'job_id': job_id})

class UpstreamError(Exception):
    def __init__(self, code, body):
        self.code, self.body = code, body
        super().__init__(f'{code}: {str(body)[:200]}')

# ---------- styles ----------
STYLES = {'groups': [], 'styles': []}
def load_styles():
    p = os.path.join(WORKDIR, 'cfg_DATA_AI_ART.json')
    if not os.path.exists(p):
        return
    try:
        d = json.load(open(p, encoding='utf-8', errors='replace'))
    except Exception as e:
        print('[styles] load fail', e)
        return
    items = d.get('data') if isinstance(d, dict) else d
    groups, styles = [], []
    for g in items or []:
        if not isinstance(g, dict):
            continue
        name = g.get('name_style') or g.get('style') or '?'
        objs = g.get('object') or []
        ids = [o.get('style') for o in objs if isinstance(o, dict) and o.get('style')]
        groups.append({'name': name, 'count': len(ids), 'styles': ids})
        styles.extend(ids)
    STYLES['groups'], STYLES['styles'] = groups, styles
    print(f'[styles] {len(groups)} groups / {len(styles)} styles')
load_styles()

# ---------- image input helpers ----------
def _bytes_from_data_url(s):
    m = re.match(r'^data:([^;,]+)?(;base64)?,(.*)$', s, re.S)
    if not m:
        return None
    payload = m.group(3)
    if m.group(2):
        return base64.b64decode(payload)
    return urllib.parse.unquote_to_bytes(payload) if hasattr(urllib, 'parse') else payload.encode()

def image_from_request(req):
    """支持 image / image_url / images[0]，data URL 或 http(s) URL。"""
    cand = req.get('image') or req.get('image_url')
    if not cand and isinstance(req.get('images'), list) and req['images']:
        cand = req['images'][0]
    if not cand or not isinstance(cand, str):
        return None
    if cand.startswith('data:'):
        return _bytes_from_data_url(cand)
    if cand.startswith('http'):
        return _opener.open(urllib.request.Request(cand, headers={'User-Agent': 'okhttp/4.9.3'}),
                            timeout=60).read()
    try:
        return base64.b64decode(cand)
    except Exception:
        return None

# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, fmt, *args):
        print('[http]', fmt % args)

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _auth_ok(self):
        return self.headers.get('Authorization', '') == 'Bearer ' + API_KEY

    def do_GET(self):
        if self.path == '/health':
            return self._json(200, {'status': 'ok', 'pool': len(pool.tokens),
                                    'device': DEVICE_SERIAL})
        if self.path == '/v1/models':
            return self._json(200, {'object': 'list', 'data': [
                {'id': 'genius-art', 'object': 'model', 'owned_by': 'amobear',
                 'description': '文生图 512x512 同步'},
                {'id': 'genius-art-styled', 'object': 'model', 'owned_by': 'amobear',
                 'description': '图生风格 1152x1536（需 input image + style）'},
            ]})
        if self.path == '/styles' or self.path.startswith('/styles/groups'):
            return self._json(200, {'total': len(STYLES['styles']),
                                    'groups': STYLES['groups']})
        self._json(404, {'error': 'not found'})

    def _parse_body(self):
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length) if length else b''
        ctype = self.headers.get('Content-Type', '')
        if ctype.startswith('multipart/form-data'):
            return self._parse_multipart(raw, ctype)
        return json.loads(raw or b'{}')

    @staticmethod
    def _parse_multipart(raw, ctype):
        """极简 multipart 解析：返回 {field: bytes|str}"""
        m = re.search(r'boundary=([^;]+)', ctype)
        if not m:
            return {}
        boundary = b'--' + m.group(1).strip('"').encode()
        out = {}
        for part in raw.split(boundary):
            if b'\r\n\r\n' not in part:
                continue
            head, body = part.split(b'\r\n\r\n', 1)
            body = body.rstrip(b'\r\n-')
            nm = re.search(rb'name="([^"]+)"', head)
            if not nm:
                continue
            name = nm.group(1).decode()
            if re.search(rb'filename="', head):
                out[name] = body
            else:
                out[name] = body.decode('utf-8', 'replace')
        return out

    def do_POST(self):
        if self.path not in ('/v1/images/generations', '/v1/images/edits'):
            return self._json(404, {'error': 'not found'})
        if not self._auth_ok():
            return self._json(401, {'error': 'bad api key'})
        try:
            req = self._parse_body()
            prompt = req.get('prompt') or ''
            if isinstance(req.get('input'), str) and not prompt:
                prompt = req['input']
            model = (req.get('model') or 'genius-art').strip()
            if isinstance(prompt, bytes):
                prompt = prompt.decode('utf-8', 'replace')

            if model in ('genius-art-styled', 'genius-art-style', 'predict-art'):
                img = req.get('image') if isinstance(req.get('image'), bytes) else None
                if img is None:
                    img = image_from_request(req) if isinstance(req, dict) else None
                if not img:
                    return self._json(400, {'error': 'genius-art-styled requires input image '
                                                     '(json: image=base64/data-url/http-url, or multipart: image=file)'})
                style = req.get('style') or 'AM_01_v2'
                if style not in STYLES['styles'] and STYLES['styles']:
                    return self._json(400, {'error': f'unknown style {style!r}, GET /styles for list'})
                t0 = time.time()
                urls = generate_styled(prompt, style,
                                       skin_color=req.get('skin_color', 0),
                                       num_image=int(req.get('n', 1) or 1),
                                       image_bytes=img, tier=str(req.get('tier', '1')))
                print(f'[styled] {time.time()-t0:.1f}s style={style} imgs={len(urls)}')
                return self._json(200, {'created': int(time.time()),
                                        'data': [{'url': u} for u in urls]})

            # 默认: 文生图
            if not prompt:
                return self._json(400, {'error': 'prompt required'})
            n = min(int(req.get('n', 1) or 1), 4)
            results = []
            for _ in range(n):
                t0 = time.time()
                urls = generate(prompt, str(req.get('tier', '1')))
                print(f'[t2i] {time.time()-t0:.1f}s prompt={prompt[:40]!r} imgs={len(urls)}')
                results += [{'url': u} for u in urls]
            return self._json(200, {'created': int(time.time()), 'data': results})

        except UpstreamError as e:
            code = e.code if isinstance(e.code, int) and 400 <= e.code < 600 else 502
            return self._json(code, {'error': str(e)})
        except urllib.error.HTTPError as e:
            return self._json(502, {'error': f'upstream {e.code}: {e.read()[:200]}'})
        except Exception as e:
            return self._json(500, {'error': str(e)})

if __name__ == '__main__':
    print('[warmup] fetching first token...')
    pool.get()
    print(f'[ready] http://127.0.0.1:{APP_PORT}  key={API_KEY}')
    print(f'        GET  /v1/models | /styles | /health')
    print(f'        POST /v1/images/generations | /v1/images/edits')
    ThreadingHTTPServer(('127.0.0.1', APP_PORT), Handler).serve_forever()
