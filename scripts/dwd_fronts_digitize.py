#!/usr/bin/env python3
"""Оцифровка фронтов с цветных карт DWD/FU Berlin (opendata.dwd.de/weather/charts).
Типы карт по размеру: forecast ico_tkb_na 1280x910; analysis ana_bwkman_dwdna 4389x3114 (RGBA).
Цвет линии: красный=тёплый, синий=холодный, фиолетовый=окклюзия, чередование красный/синий = стационарный (stat).
Выход: GeoJSON (LineString + kind) в lon/lat и отладочная картинка.
Проекция (полярная стереография, y вниз): x=x0+k*2tan(colat/2)*sin(dl), y=y0+k*2tan(colat/2)*cos(dl); параметры в долях ширины."""
import sys, json, numpy as np, cv2
from collections import deque
from skimage.morphology import skeletonize
from skimage.measure import label, regionprops

CHARTS = {
    "fc":  dict(size=(1280, 910),  lon0=6.2,  k=903.6/1280,  x0=765.6/1280,  y0=-122.4/1280,
                excl=[(0.86, 1.0, 0.88, 1.0), (0.80, 1.0, 0.0, 0.22)]),     # (y0,y1,x0,x1) в долях: лого DWD, легенда
    "ana": dict(size=(4389, 3114), lon0=9.44, k=3233.04/4389, x0=2767.47/4389, y0=-569.6/4389,
                excl=[(0.89, 1.0, 0.0, 0.17), (0.0, 1.0, 0.0, 0.012)]),
}
MIN_LEN = 60        # px при ширине 1280 (масштабируется): минимальная длина компоненты (отсекает подписи систем)
CLOSE = 41          # склейка разрывов на месте значков
KIND_MIN_RUN = 40   # короткие вставки другого цвета схлопываются
STAT_RUN_MAX = 120  # чередующиеся warm/cold куски короче этого = стационарный фронт
SMOOTH_WIN = 9      # окно сглаживания (в точках)

def detect_chart(w, h):
    for k, c in CHARTS.items():
        if abs(c["size"][0]-w) < 3 and abs(c["size"][1]-h) < 3: return k
    raise ValueError("неизвестный размер карты %dx%d" % (w, h))

def inv_proj(x, y, W, c):
    k = c["k"]*W; dx = (np.asarray(x, float)-c["x0"]*W)/k; dy = (np.asarray(y, float)-c["y0"]*W)/k
    R = np.hypot(dx, dy)
    return c["lon0"]+np.degrees(np.arctan2(dx, dy)), 90-np.degrees(2*np.arctan(R/2))

def load_rgb(path):
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im.ndim == 3 and im.shape[2] == 4:
        a = im[..., 3:4].astype(float)/255; im = (im[..., :3]*a+255*(1-a)).astype(np.uint8)
    return im

def color_masks(im, c):
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV); H, S, V = [hsv[..., i].astype(int) for i in range(3)]
    red = ((H < 8) | (H > 172)) & (S > 150) & (V > 150)
    blue = (H > 100) & (H < 130) & (S > 150) & (V > 150)
    viol = (H > 135) & (H < 168) & (S > 40) & (S < 200) & (V > 200)
    h, w = H.shape; ex = np.zeros((h, w), bool)
    for (a, b, x0, x1) in c["excl"]: ex[int(h*a):int(h*b), int(w*x0):int(w*x1)] = True
    return {"warm": red & ~ex, "cold": blue & ~ex, "occl": viol & ~ex}

BORDER_MIN = 25     # у края карты фронт обрезан рамкой — разрешаем короткие куски (px при ширине 1280)
def near_border(bbox, shape, s):
    m = int(8*s); return bbox[0] < m or bbox[1] < m or bbox[2] > shape[0]-m or bbox[3] > shape[1]-m

def drop_small(m, minlen, s):
    m8 = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)); lab = label(m8, connectivity=2)
    keep = np.zeros(m8.shape, bool)
    for r in regionprops(lab):
        need = (BORDER_MIN if near_border(r.bbox, m8.shape, s) else minlen)*s
        if max(r.bbox[2]-r.bbox[0], r.bbox[3]-r.bbox[1]) >= need: keep |= lab == r.label
    return keep

NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
def longest_path(pix):
    S = set(pix); adj = {p: [(p[0]+a, p[1]+b) for a, b in NB if (p[0]+a, p[1]+b) in S] for p in S}
    def bfs(s):
        prev = {s: None}; q = deque([s]); last = s
        while q:
            u = q.popleft(); last = u
            for v in adj[u]:
                if v not in prev: prev[v] = u; q.append(v)
        return last, prev
    a, _ = bfs(pix[0]); b, prev = bfs(a); path = []; u = b
    while u is not None: path.append(u); u = prev[u]
    return path[::-1]

def classify(path, kmap):
    kinds = list(kmap); dts = [cv2.distanceTransform((~kmap[k]).astype(np.uint8), cv2.DIST_L2, 3) for k in kinds]
    return [kinds[int(np.argmin([d[r, c] for d in dts]))] for (r, c) in path]

def runs(lbl):
    res = []; i = 0
    while i < len(lbl):
        j = i
        while j < len(lbl) and lbl[j] == lbl[i]: j += 1
        res.append([lbl[i], i, j]); i = j
    return res

def mark_stationary(lbl, s):
    """>=4 подряд чередующихся warm/cold кусков, каждый короче STAT_RUN_MAX -> 'stat' (проверено только синтетически)."""
    rs = runs(lbl); i = 0
    while i < len(rs):
        j = i
        while (j+1 < len(rs) and {rs[j][0], rs[j+1][0]} == {"warm", "cold"}
               and rs[j][2]-rs[j][1] < STAT_RUN_MAX*s and rs[j+1][2]-rs[j+1][1] < STAT_RUN_MAX*s): j += 1
        if j-i+1 >= 4:
            for t in range(i, j+1): lbl[rs[t][1]:rs[t][2]] = ["stat"]*(rs[t][2]-rs[t][1])
        i = j+1
    return lbl

def smooth_runs(lbl, s):
    changed = True
    while changed:
        changed = False; rs = runs(lbl)
        for idx, (k, a, b) in enumerate(rs):
            if k != "stat" and b-a < KIND_MIN_RUN*s and len(rs) > 1:
                nb = [rs[idx-1]] if idx > 0 else []; nb += [rs[idx+1]] if idx+1 < len(rs) else []
                new = max(nb, key=lambda r: r[2]-r[1])[0]; lbl[a:b] = [new]*(b-a); changed = True; break
    return lbl

def smooth_xy(xs, ys, win):
    if len(xs) < win+2: return xs, ys
    k = np.ones(win)/win; pad = win//2
    f = lambda v: np.convolve(np.pad(v, pad, mode="edge"), k, mode="valid")
    xs2, ys2 = f(xs), f(ys); xs2[0], ys2[0], xs2[-1], ys2[-1] = xs[0], ys[0], xs[-1], ys[-1]
    return xs2, ys2

def digitize(path_img, kind=None):
    im = load_rgb(path_img); h, w = im.shape[:2]; kind = kind or detect_chart(w, h); c = CHARTS[kind]; s = w/1280.0
    cm = {k: drop_small(v, MIN_LEN, s) for k, v in color_masks(im, c).items()}
    allm = (cm["warm"] | cm["cold"] | cm["occl"]).astype(np.uint8)
    e = int(CLOSE*s) | 1
    line = cv2.morphologyEx(allm, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (e, e)))
    skel = skeletonize(line > 0); lab = label(skel, connectivity=2); feats = []; dbg = np.full(im.shape, 255, np.uint8)
    col = {"warm": (0, 0, 255), "cold": (255, 0, 0), "occl": (200, 0, 200), "stat": (0, 160, 0)}; fid = 0
    work = [[tuple(p) for p in r.coords] for r in regionprops(lab)]
    rad = max(2, int(2*s))
    while work:
        pix = work.pop()
        if len(pix) < BORDER_MIN*s: continue
        path = longest_path(pix); ys0 = np.array([p[0] for p in path]); xs0 = np.array([p[1] for p in path])
        need = (BORDER_MIN if near_border((ys0.min(), xs0.min(), ys0.max(), xs0.max()), im.shape, s) else MIN_LEN)*s
        if len(path) >= need:
            lbl = smooth_runs(mark_stationary(classify(path, cm), s), s)
            for (k, a, b) in runs(lbl):
                seg = path[max(a-1, 0):b]
                if len(seg) < 3: continue
                ys = np.array([p[0] for p in seg], float); xs = np.array([p[1] for p in seg], float)
                xs, ys = smooth_xy(xs, ys, SMOOTH_WIN*max(1, int(s)))
                step = max(1, int(3*s)); idx = list(range(0, len(xs), step)); idx += [len(xs)-1] if idx[-1] != len(xs)-1 else []
                lon, lat = inv_proj(xs[idx], ys[idx], w, c)
                feats.append({"type": "Feature", "properties": {"kind": k, "line": fid, "px_len": len(seg)},
                              "geometry": {"type": "LineString", "coordinates": [[round(float(a_), 3), round(float(b_), 3)] for a_, b_ in zip(lon, lat)]}})
                for y, x in zip(ys, xs): cv2.circle(dbg, (int(x), int(y)), max(1, int(s)), col[k], -1)
            fid += 1
        # ответвления: убираем найденный путь (с окрестностью) и ищем в остатке ещё линии
        used = set()
        for (r_, c_) in path:
            for dr in range(-rad, rad+1):
                for dc in range(-rad, rad+1): used.add((r_+dr, c_+dc))
        rest = [p for p in pix if p not in used]
        if len(rest) >= BORDER_MIN*s:
            sub = np.zeros(im.shape[:2], np.uint8); rr = np.array([p[0] for p in rest]); cc = np.array([p[1] for p in rest]); sub[rr, cc] = 1
            l2 = label(sub, connectivity=2)
            for r2 in regionprops(l2): work.append([tuple(p) for p in r2.coords])
    return {"type": "FeatureCollection", "properties": {"chart": kind, "src": path_img.split("/")[-1]}, "features": feats}, dbg

if __name__ == "__main__":
    fc, dbg = digitize(sys.argv[1]); out = sys.argv[2] if len(sys.argv) > 2 else "out/fronts.geojson"
    json.dump(fc, open(out, "w")); cv2.imwrite(out.replace(".geojson", "_dbg.png"), dbg)
    for f in fc["features"]: print(f["properties"], f["geometry"]["coordinates"][0], "->", f["geometry"]["coordinates"][-1])
