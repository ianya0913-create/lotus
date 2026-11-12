"""
LoTUS-BF 本地替代後端
====================
老師的伺服器連不上時，用 neurosynth_dataset.pkl.gz 轉出來的資料，在自己電腦上提供「同樣的 API」。
前端（React）完全不用改，只要把 vite.config.js 的 proxy 指到 http://localhost:5050。

需要：Python 3.8+ 和 numpy（scipy 有裝的話平滑會比較快，沒裝也能跑）
執行：python server.py          （預設 port 5050）
     python server.py 6000     （指定其他 port）

提供的 API（和老師的 app.py 一樣）：
  GET /terms                         所有詞彙
  GET /terms/<term>                  相關詞彙（共現次數、Jaccard）
  GET /query/<q>/studies             符合查詢的論文
  GET /query/<q>/locations           符合查詢的論文的所有座標
  GET /query/<q>/nii                 座標密度圖（.nii.gz）
  GET /help                          說明

和老師版本的差異：
  - 詞彙比對用的是 Neurosynth 的 TF-IDF 標註（tfidf > 0 就算符合），
    老師的版本是對摘要做全文搜尋，所以結果數量會有些差異。
  - 不在詞彙表裡的詞會找不到論文，回應的 "unknown_terms" 會列出這些詞。
"""
import gzip
import json
import os
import re
import struct
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

try:
    from scipy.ndimage import gaussian_filter
    HAS_SCIPY = True
except Exception:
    HAS_SCIPY = False

import mimetypes

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')

# 前端打包後的靜態檔（npm run build 產生的 dist）。在 Render 上同一個服務一起提供。
# 可用環境變數 FRONTEND_DIST 指定；預設是 ../lotus-bf/dist
FRONTEND_DIST = os.environ.get('FRONTEND_DIST') or os.path.join(HERE, '..', 'lotus-bf', 'dist')
FRONTEND_DIST = os.path.abspath(FRONTEND_DIST)
BASE = '/lotus-bf'   # 前端的 base path（對應 vite.config.js 的 base）

# ---------------------------------------------------------------- 載入資料
t0 = time.time()
with open(os.path.join(DATA, 'metadata.json'), encoding='utf8') as f:
    METADATA = json.load(f)                       # list[dict]，第 i 筆 = 第 i 篇論文
N_STUDIES = len(METADATA)

_t = np.load(os.path.join(DATA, 'terms.npz'))
TERM_NAMES = [str(s) for s in _t['names']]
TERM_PTR = _t['ptr']                              # 第 j 個詞的論文在 study_idx[ptr[j]:ptr[j+1]]
TERM_STUDY_IDX = _t['study_idx']
TERM_INDEX = {name: j for j, name in enumerate(TERM_NAMES)}

_c = np.load(os.path.join(DATA, 'coords.npz'))
COORD_ROW = _c['study_row']                       # 每個座標屬於第幾篇論文（已排序）
COORD_XYZ = _c['xyz'].astype(np.float32)          # (n, 3) MNI 座標，單位 mm
COORD_START = np.searchsorted(COORD_ROW, np.arange(N_STUDIES + 1))   # 每篇論文座標的起點

# 每個詞出現在幾篇論文（算 Jaccard 用）
TERM_DF = np.diff(TERM_PTR)

# 前端顯示的詞彙清單：和老師的版本一樣，排除數字開頭的詞
PUBLIC_TERMS = sorted(t for t in TERM_NAMES if not re.match(r'^\d', t))

print(f'[data] {N_STUDIES} studies, {len(TERM_NAMES)} terms, {len(COORD_ROW)} coordinates '
      f'loaded in {time.time() - t0:.1f}s (scipy={"yes" if HAS_SCIPY else "no"})')


# ---------------------------------------------------------------- 查詢解析
def normalize_query(expr):
    expr = re.sub(r'(?i)\b(NOT|AND|OR)(?=[^\s()])', r'\1 ', expr)
    return re.sub(r'\s+', ' ', expr).strip()


TOKEN_RE = re.compile(r'\[[^\]]*\]|"[^"]*"|\(|\)|[^\s()\[\]"]+')
OPS = {'AND', 'OR', 'NOT'}


def tokenize(expr):
    """把查詢字串切成 token；連續的一般字詞會盡量合併成詞彙表裡的多字詞（例如 working memory）。"""
    raw = TOKEN_RE.findall(normalize_query(expr))
    out = []
    i = 0
    while i < len(raw):
        tok = raw[i]
        up = tok.upper()
        if tok in ('(', ')') or up in OPS:
            out.append(('OP', up) if up in OPS else ('PAREN', tok))
            i += 1
        elif tok.startswith('['):
            nums = re.findall(r'-?\d+(?:\.\d+)?', tok)
            if len(nums) != 3:
                raise ValueError(f'座標格式錯誤：{tok}（應為 [x,y,z]）')
            out.append(('COORD', tuple(float(v) for v in nums)))
            i += 1
        elif tok.startswith('"'):
            out.append(('TERM', tok.strip('"').strip().lower()))
            i += 1
        else:
            # 往後最多看 3 個字，取詞彙表裡最長的組合
            words = []
            j = i
            while j < len(raw) and j < i + 3:
                w = raw[j]
                if w in ('(', ')') or w.upper() in OPS or w.startswith('[') or w.startswith('"'):
                    break
                words.append(w.lower())
                j += 1
            for n in range(len(words), 0, -1):
                cand = ' '.join(words[:n])
                if cand in TERM_INDEX or n == 1:
                    out.append(('TERM', cand))
                    i += n
                    break
    return out


class Parser:
    """布林查詢：OR < AND < NOT；相鄰的兩個運算元之間預設是 AND。
    每個節點求值後是一個長度 = 論文數 的 True/False 陣列。"""

    def __init__(self, tokens, r):
        self.toks = tokens
        self.pos = 0
        self.r = r
        self.unknown = []
        self.has_terms = False
        self.has_loc = False

    def peek(self):
        return self.toks[self.pos] if self.pos < len(self.toks) else None

    def take(self):
        tok = self.peek()
        self.pos += 1
        return tok

    def starts_operand(self, tok):
        return tok is not None and (tok[0] in ('TERM', 'COORD') or tok == ('PAREN', '(') or tok == ('OP', 'NOT'))

    def parse(self):
        if not self.toks:
            raise ValueError('查詢是空的')
        mask = self.parse_or()
        if self.peek() is not None:
            raise ValueError(f'查詢語法錯誤，多出：{self.peek()[1]}')
        return mask

    def parse_or(self):
        mask = self.parse_and()
        while self.peek() == ('OP', 'OR'):
            self.take()
            mask = mask | self.parse_and()
        return mask

    def parse_and(self):
        mask = self.parse_unary()
        while True:
            tok = self.peek()
            if tok == ('OP', 'AND'):
                self.take()
                mask = mask & self.parse_unary()
            elif self.starts_operand(tok):          # 隱含的 AND
                mask = mask & self.parse_unary()
            else:
                return mask

    def parse_unary(self):
        if self.peek() == ('OP', 'NOT'):
            self.take()
            return ~self.parse_unary()
        return self.parse_primary()

    def parse_primary(self):
        tok = self.take()
        if tok is None:
            raise ValueError('查詢不完整')
        kind, val = tok
        if tok == ('PAREN', '('):
            mask = self.parse_or()
            if self.take() != ('PAREN', ')'):
                raise ValueError('括號沒有配對')
            return mask
        if kind == 'TERM':
            self.has_terms = True
            return self.term_mask(val)
        if kind == 'COORD':
            self.has_loc = True
            return self.coord_mask(val)
        raise ValueError(f'這裡不應該出現：{val}')

    def term_mask(self, term):
        mask = np.zeros(N_STUDIES, dtype=bool)
        j = TERM_INDEX.get(term)
        if j is None:
            self.unknown.append(term)
            return mask
        mask[TERM_STUDY_IDX[TERM_PTR[j]:TERM_PTR[j + 1]]] = True
        return mask

    def coord_mask(self, xyz):
        d2 = ((COORD_XYZ - np.array(xyz, dtype=np.float32)) ** 2).sum(axis=1)
        mask = np.zeros(N_STUDIES, dtype=bool)
        mask[COORD_ROW[d2 < self.r * self.r]] = True
        return mask


def run_query(q, r):
    p = Parser(tokenize(q), r)
    mask = p.parse()
    return np.nonzero(mask)[0], p


# ---------------------------------------------------------------- NIfTI
SHAPE = (91, 109, 91)
AFFINE = np.array([[-2, 0, 0, 90], [0, 2, 0, -126], [0, 0, 2, -72], [0, 0, 0, 1]], dtype=float)


def smooth(vol, sigma):
    if sigma <= 0:
        return vol
    if HAS_SCIPY:
        return gaussian_filter(vol, sigma=sigma, mode='constant', truncate=3.0)
    rad = int(np.ceil(3 * sigma))
    k = np.exp(-(np.arange(-rad, rad + 1) ** 2) / (2 * sigma * sigma))
    k /= k.sum()
    out = vol
    for axis in range(3):
        out = np.apply_along_axis(lambda v: np.convolve(v, k, mode='same'), axis, out)
    return out.astype(np.float32)


def make_nii(rows, fwhm):
    vol = np.zeros(SHAPE, dtype=np.float32)
    idx = np.concatenate([np.arange(COORD_START[s], COORD_START[s + 1]) for s in rows]) if len(rows) else np.array([], int)
    if len(idx):
        xyz = COORD_XYZ[idx].astype(float)
        ijk = np.rint((np.linalg.inv(AFFINE) @ np.c_[xyz, np.ones(len(xyz))].T)[:3].T).astype(int)
        ok = np.all((ijk >= 0) & (ijk < np.array(SHAPE)), axis=1)
        np.add.at(vol, tuple(ijk[ok].T), 1.0)
    if fwhm and fwhm > 0:
        vol = smooth(vol, (fwhm / (2 * np.sqrt(2 * np.log(2)))) / 2.0)
    return nifti_bytes(vol.astype(np.float32))


def nifti_bytes(vol):
    """手寫一個最基本的 NIfTI-1 檔（348 bytes 標頭 + 4 bytes 擴充 + float32 資料），不需要 nibabel。"""
    hdr = bytearray(348)
    struct.pack_into('<i', hdr, 0, 348)                                  # sizeof_hdr
    struct.pack_into('<8h', hdr, 40, 3, *SHAPE, 1, 1, 1, 1)               # dim
    struct.pack_into('<h', hdr, 70, 16)                                   # datatype = FLOAT32
    struct.pack_into('<h', hdr, 72, 32)                                   # bitpix
    struct.pack_into('<8f', hdr, 76, -1.0, 2, 2, 2, 1, 1, 1, 1)           # pixdim（qfac = -1）
    struct.pack_into('<f', hdr, 108, 352.0)                               # vox_offset
    struct.pack_into('<f', hdr, 112, 1.0)                                 # scl_slope
    struct.pack_into('<f', hdr, 116, 0.0)                                 # scl_inter
    hdr[123] = 2 | 8                                                      # xyzt_units：mm、sec
    struct.pack_into('<2f', hdr, 124, float(vol.max()), float(vol.min())) # cal_max / cal_min
    struct.pack_into('<2h', hdr, 252, 4, 4)                               # qform_code, sform_code = MNI
    # quaternion：繞 y 轉 180 度 + qfac -1 → 只有 x 軸翻轉
    struct.pack_into('<6f', hdr, 256, 0.0, 1.0, 0.0, 90.0, -126.0, -72.0)
    struct.pack_into('<4f', hdr, 280, *AFFINE[0])                         # srow_x
    struct.pack_into('<4f', hdr, 296, *AFFINE[1])                         # srow_y
    struct.pack_into('<4f', hdr, 312, *AFFINE[2])                         # srow_z
    hdr[344:348] = b'n+1\x00'
    body = bytes(hdr) + b'\x00' * 4 + vol.tobytes(order='F')              # NIfTI 是 x 變化最快
    return gzip.compress(body, compresslevel=6)


# ---------------------------------------------------------------- HTTP
def int_arg(qs, name, default=None):
    try:
        return int(qs[name][0])
    except (KeyError, ValueError, IndexError):
        return default


def float_arg(qs, name, default):
    try:
        return float(qs[name][0])
    except (KeyError, ValueError, IndexError):
        return default


def page(items, qs):
    offset = max(0, int_arg(qs, 'offset', 0) or 0)
    limit = int_arg(qs, 'limit')
    items = items[offset:]
    return items[:limit] if limit is not None and limit >= 0 else items


def related_terms(term, qs):
    j = TERM_INDEX.get(term.lower())
    if j is None:
        return {'term': term, 'related': [], 'error': 'unknown term'}
    a = np.zeros(N_STUDIES, dtype=bool)
    a[TERM_STUDY_IDX[TERM_PTR[j]:TERM_PTR[j + 1]]] = True
    hit = a[TERM_STUDY_IDX]                                       # 每個 (詞, 論文) 配對的論文是否在 a 裡
    co = np.add.reduceat(hit.astype(np.int64), TERM_PTR[:-1]) * (TERM_DF > 0)
    co[j] = 0
    n_a = int(a.sum())
    with np.errstate(divide='ignore', invalid='ignore'):
        jac = co / (n_a + TERM_DF - co)
    order = np.lexsort((np.array(TERM_NAMES), -co, -np.nan_to_num(jac)))
    rel = [{'term': TERM_NAMES[k], 'co_count': int(co[k]), 'jaccard': float(jac[k])}
           for k in order if co[k] > 0 and not re.match(r'^\d', TERM_NAMES[k])]
    return {'term': term, 'related': page(rel, qs)}


QUERY_RE = re.compile(r'^/query/(.+)/(studies|locations|nii)$')


class Handler(BaseHTTPRequestHandler):
    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        path = url.path.rstrip('/') or '/'
        qs = urllib.parse.parse_qs(url.query)
        try:
            if path == '/terms':
                return self.send_json({'terms': PUBLIC_TERMS})
            if path.startswith('/terms/'):
                term = urllib.parse.unquote(path[len('/terms/'):])
                return self.send_json(related_terms(term, qs))
            m = QUERY_RE.match(path)
            if m:
                q = urllib.parse.unquote(m.group(1))
                kind = m.group(2)
                r = float_arg(qs, 'r', 6.0)
                rows, p = run_query(q, r)
                if kind == 'studies':
                    results = page([METADATA[i] for i in rows], qs)
                    return self.send_json({
                        'count': len(results),
                        'applied': {'locations': p.has_loc, 'terms': p.has_terms, 'r': r if p.has_loc else None},
                        'unknown_terms': p.unknown,
                        'results': results,
                    })
                if kind == 'locations':
                    out = []
                    for i in rows:
                        sid = METADATA[i]['study_id']
                        for x, y, z in COORD_XYZ[COORD_START[i]:COORD_START[i + 1]]:
                            out.append({'study_id': sid, 'x': float(x), 'y': float(y), 'z': float(z)})
                    out.sort(key=lambda d: (d['study_id'], d['x'], d['y'], d['z']))
                    out = page(out, qs)
                    return self.send_json({'location_counts': len(out),
                                           'study_counts': len({d['study_id'] for d in out}),
                                           'unknown_terms': p.unknown, 'results': out})
                body = make_nii(rows, float_arg(qs, 'fwhm', 10.0))
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Disposition', 'attachment; filename="query_mixed_map.nii.gz"')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)
                return
            if path == '/help':
                return self.send_json({'name': 'LoTUS-BF local API', 'endpoints': [
                    '/terms', '/terms/<term>', '/query/<q>/studies', '/query/<q>/locations', '/query/<q>/nii', '/help']})
            # 其餘路徑交給前端靜態檔（用 url.path 保留原始的斜線）
            return self.serve_static(url.path)
        except ValueError as e:
            return self.send_json({'error': str(e)}, 400)
        except Exception as e:  # 伺服器內部錯誤也回 JSON，前端比較好顯示
            return self.send_json({'error': f'{type(e).__name__}: {e}'}, 500)

    def serve_static(self, raw_path):
        """提供前端 dist 的靜態檔。SPA：找不到的路徑回傳 index.html。"""
        if not os.path.isdir(FRONTEND_DIST):
            return self.send_json({'error': 'frontend not built (run npm run build)'}, 404)
        # 根目錄導向前端的 base path
        if raw_path in ('/', ''):
            self.send_response(302)
            self.send_header('Location', BASE + '/')
            self.end_headers()
            return
        # 去掉 base 前綴，對應到 dist 裡的檔案（先解碼 %2f 等，避免用編碼繞過防跳脫檢查）
        raw_path = urllib.parse.unquote(raw_path)
        rel = raw_path[len(BASE):] if raw_path.startswith(BASE) else raw_path
        rel = rel.lstrip('/')
        candidate = os.path.abspath(os.path.join(FRONTEND_DIST, rel))
        # 防止 ../ 跳出 dist 資料夾
        if not candidate.startswith(FRONTEND_DIST):
            return self.send_json({'error': 'forbidden'}, 403)
        if not rel or not os.path.isfile(candidate):
            candidate = os.path.join(FRONTEND_DIST, 'index.html')   # SPA 退回首頁
        if not os.path.isfile(candidate):
            return self.send_json({'error': 'not found'}, 404)
        ctype = mimetypes.guess_type(candidate)[0] or 'application/octet-stream'
        with open(candidate, 'rb') as f:
            body = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write('[api] ' + (fmt % args) + '\n')


if __name__ == '__main__':
    # Render 會用 PORT 環境變數指定 port；本機則用參數或預設 5050
    port = int(os.environ.get('PORT') or (sys.argv[1] if len(sys.argv) > 1 else 5050))
    # 綁 0.0.0.0 才能從外部連入（Render 需要）；本機一樣可用 localhost 開啟
    host = '0.0.0.0'
    print(f'LoTUS-BF server running on {host}:{port}  (Ctrl+C to stop)')
    if os.path.isdir(FRONTEND_DIST):
        print(f'[static] serving frontend from {FRONTEND_DIST} at {BASE}/')
    else:
        print(f'[static] 前端尚未 build（找不到 {FRONTEND_DIST}）；只提供 API')
    ThreadingHTTPServer((host, port), Handler).serve_forever()
