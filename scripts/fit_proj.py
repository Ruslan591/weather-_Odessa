import json, numpy as np, cv2, sys
from scipy.optimize import minimize
S=0.25
def load_land(path='land50.geojson'):
    d=json.load(open(path)); rings=[]
    for f in d['features']:
        g=f['geometry']
        polys=[g['coordinates']] if g['type']=='Polygon' else g['coordinates']
        for p in polys:
            r=np.array(p[0])
            if r[:,1].min()>5: rings.append(r)
    return rings
def proj(lon,lat,P):
    lon0,k,x0,y0=P
    colat=np.radians(90-np.asarray(lat)); dl=np.radians(np.asarray(lon)-lon0)
    R=2*np.tan(colat/2)*k
    return x0+R*np.sin(dl), y0+R*np.cos(dl)
def render(rings,P,shape):
    m=np.zeros(shape,np.uint8)
    for r in rings:
        x,y=proj(r[:,0],r[:,1],P)
        pts=np.stack([x*S,y*S],1)
        if np.abs(pts).max()>20000: continue
        cv2.fillPoly(m,[pts.astype(np.int32)],1)
    return m
def gray_mask(path):
    im=cv2.imread(path); small=cv2.resize(im,None,fx=S,fy=S,interpolation=cv2.INTER_AREA)
    g=small.mean(2); sat=small.max(2).astype(int)-small.min(2)
    land=(g>195)&(g<235)&(sat<12); sea=(g>=245)&(sat<12)
    return land,sea
def score(P,rings,land,sea):
    m=render(rings,P,land.shape).astype(bool)
    tp=(m&land).sum(); fp=(m&sea).sum(); fn=((~m)&land).sum(); tn=((~m)&sea).sum()
    return 1-(tp+tn)/(tp+tn+fp+fn)
if __name__=='__main__':
    path=sys.argv[1]; rings=load_land(); land,sea=gray_mask(path)
    h,w=land.shape; H,W=h/S,w/S
    best=None
    for lon0 in range(-30,41,10):
      for k in (600,800,1000):
        for x0 in (W*0.35,W*0.5,W*0.65):
          for y0 in (H*1.0,H*1.3,H*1.6):
            P=np.array([lon0,k,x0,y0],float); s=score(P,rings,land,sea)
            if best is None or s<best[0]: best=(s,P)
    print('grid',best)
    P=best[1]
    for it in range(3):
        r=minimize(lambda p:score(p,rings,land,sea),P,method='Nelder-Mead',options={'xatol':0.05,'fatol':1e-5,'maxiter':400,'initial_simplex':None})
        P=r.x; print('nm',r.fun,P)
    np.save(path.split('/')[-1]+'.proj.npy',P)
