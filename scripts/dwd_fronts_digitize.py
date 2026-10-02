#!/usr/bin/env python3
"""Оцифровка фронтов с цветной прогнозной карты DWD/FU Berlin (ico_tkb_na).
Цвет линии: красный=тёплый, синий=холодный, фиолетовый=окклюзия.
Вход: PNG/WebP карты. Выход: GeoJSON (LineString + kind) и отладочная картинка.
Проекция: полярная стереографическая, параметры (lon0, k, x0, y0) в долях ширины картинки (калибруются fit-скриптом)."""
import sys, json, numpy as np, cv2
from collections import deque
from skimage.morphology import skeletonize
from skimage.measure import label, regionprops

# калибровка по реальному ico_tkb_na 1280x910 с opendata (проверено 02.10.2026)
PROJ = dict(lon0=6.2, k=903.6/1280, x0=765.6/1280, y0=-122.4/1280)
MIN_LEN_PX = 60          # минимальная длина компоненты (отсекает подписи систем)
CLOSE_PX = 41            # склейка разрывов на месте значков
KIND_MIN_RUN_PX = 40     # короткие вставки другого цвета схлопываются

def inv_proj(x, y, W):
    k=PROJ['k']*W; dx=(np.asarray(x)-PROJ['x0']*W)/k; dy=(np.asarray(y)-PROJ['y0']*W)/k
    R=np.hypot(dx,dy); lat=90-np.degrees(2*np.arctan(R/2)); lon=PROJ['lon0']+np.degrees(np.arctan2(dx,dy))
    return lon, lat

def color_masks(im):
    hsv=cv2.cvtColor(im,cv2.COLOR_BGR2HSV); H,S,V=[hsv[...,i].astype(int) for i in range(3)]
    red=((H<8)|(H>172))&(S>150)&(V>150)
    blue=(H>100)&(H<130)&(S>150)&(V>150)
    viol=(H>135)&(H<168)&(S>40)&(S<200)&(V>200)
    h,w=H.shape
    excl=np.zeros_like(red); excl[int(h*0.86):, int(w*0.88):]=True; excl[int(h*0.80):, :int(w*0.22)]=True  # логотип DWD, легенда
    return {'warm':red&~excl,'cold':blue&~excl,'occl':viol&~excl}

def drop_small(m, minlen):
    m8=cv2.morphologyEx(m.astype(np.uint8),cv2.MORPH_CLOSE,np.ones((3,3),np.uint8)); lab=label(m8,connectivity=2); keep=np.zeros(m8.shape,bool)
    for r in regionprops(lab):
        if max(r.bbox[2]-r.bbox[0], r.bbox[3]-r.bbox[1])>=minlen: keep|=lab==r.label
    return keep

def strip_symbols(m):
    """убрать значки (полукруги/треугольники): толщина линии ~2-3 px, значки ~10+ px."""
    m8=m.astype(np.uint8); blobs=cv2.morphologyEx(m8,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7)))
    return m&~blobs.astype(bool)

NB=[(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
def longest_path(pix):
    S=set(pix); adj={p:[(p[0]+a,p[1]+b) for a,b in NB if (p[0]+a,p[1]+b) in S] for p in S}
    def bfs(s):
        prev={s:None}; q=deque([s]); last=s
        while q:
            u=q.popleft(); last=u
            for v in adj[u]:
                if v not in prev: prev[v]=u; q.append(v)
        return last,prev
    a,_=bfs(pix[0]); b,prev=bfs(a); path=[]; u=b
    while u is not None: path.append(u); u=prev[u]
    return path[::-1]

def classify(path, kmap):
    """kmap: dict kind->bool mask; тип каждой точки пути по ближайшему цветному пикселю."""
    kinds=list(kmap); 
    dts=[cv2.distanceTransform((~kmap[k]).astype(np.uint8),cv2.DIST_L2,3) for k in kinds]
    out=[]
    for (r,c) in path: out.append(kinds[int(np.argmin([d[r,c] for d in dts]))])
    return out

def runs(lbl):
    res=[]; i=0
    while i<len(lbl):
        j=i
        while j<len(lbl) and lbl[j]==lbl[i]: j+=1
        res.append([lbl[i],i,j]); i=j
    return res

def smooth_runs(lbl):
    changed=True
    while changed:
        changed=False; rs=runs(lbl)
        for idx,(k,a,b) in enumerate(rs):
            if b-a<KIND_MIN_RUN_PX and len(rs)>1:
                nb=[rs[idx-1][0]] if idx>0 else []; nb+= [rs[idx+1][0]] if idx+1<len(rs) else []
                new=max(set(nb),key=lambda t:sum(r[2]-r[1] for r in rs if r[0]==t and abs(rs.index(r)-idx)==1)) 
                lbl[a:b]=[new]*(b-a); changed=True; break
    return lbl

def digitize(path_img):
    im=cv2.imread(path_img); h,w=im.shape[:2]
    cm={k:drop_small(v,MIN_LEN_PX) for k,v in color_masks(im).items()}
    allm=cm['warm']|cm['cold']|cm['occl']
    line=strip_symbols(allm)
    line=cv2.morphologyEx(line.astype(np.uint8),cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(CLOSE_PX,CLOSE_PX)))
    skel=skeletonize(line>0); lab=label(skel,connectivity=2); feats=[]; dbg=np.full(im.shape,255,np.uint8)
    col={'warm':(0,0,255),'cold':(255,0,0),'occl':(200,0,200)}
    for r in regionprops(lab):
        pix=[tuple(p) for p in r.coords]
        if len(pix)<MIN_LEN_PX: continue
        path=longest_path(pix); lbl=smooth_runs(classify(path,cm))
        for (kind,a,b) in runs(lbl):
            seg=path[max(a-1,0):b]
            if len(seg)<3: continue
            ys=np.array([p[0] for p in seg]); xs=np.array([p[1] for p in seg])
            lon,lat=inv_proj(xs[::3].tolist()+[xs[-1]], ys[::3].tolist()+[ys[-1]], w)
            feats.append({"type":"Feature","properties":{"kind":kind,"px_len":len(seg)},"geometry":{"type":"LineString","coordinates":[[round(float(a),3),round(float(b),3)] for a,b in zip(lon,lat)]}})
            for y,x in seg: cv2.circle(dbg,(int(x),int(y)),1,col[kind],-1)
    return {"type":"FeatureCollection","features":feats}, dbg

if __name__=='__main__':
    fc,dbg=digitize(sys.argv[1]); out=sys.argv[2] if len(sys.argv)>2 else 'out/fronts.geojson'
    json.dump(fc,open(out,'w')); cv2.imwrite(out.replace('.geojson','_dbg.png'),dbg)
    for f in fc['features']: print(f['properties'],f['geometry']['coordinates'][0],'->',f['geometry']['coordinates'][-1])
