import numpy as np, cv2, sys
from scipy.ndimage import distance_transform_edt
from scipy.optimize import minimize
import fit_proj as F
S=0.25
path=sys.argv[1]
im=cv2.imread(path); h0,w0=im.shape[:2]
F.S=S; land,sea=F.gray_mask(path)
k3=np.ones((3,3),np.uint8)
edge=(cv2.dilate(land.astype(np.uint8),k3)&cv2.dilate(sea.astype(np.uint8),k3)).astype(bool)
dt=distance_transform_edt(~edge)
rings=F.load_land()
pts=np.concatenate([r[::2] for r in rings])
pts=pts[(pts[:,1]>20)&(pts[:,1]<75)&(pts[:,0]>-45)&(pts[:,0]<70)]
def cost(P):
    x,y=F.proj(pts[:,0],pts[:,1],P); x*=S; y*=S
    ok=(x>3)&(x<dt.shape[1]-3)&(y>3)&(y<dt.shape[0]-3)
    if ok.sum()<200: return 50
    d=dt[y[ok].astype(int),x[ok].astype(int)]
    return np.minimum(d,8).mean()+ 8*(1-ok.mean())*0.2
best=[]
rng=np.random.default_rng(0)
for lon0 in range(-40,41,5):
  for k in (700,900,1100,1300):
    for x0 in np.linspace(200,1200,6):
      for y0 in np.linspace(-1800,200,8):
        P=np.array([lon0,k,x0,y0],float); best.append((cost(P),tuple(P)))
best.sort()
res=[]
for c,P in best[:12]:
    q=minimize(cost,np.array(P),method='Nelder-Mead',options={'xatol':0.05,'fatol':1e-5,'maxiter':500})
    res.append((q.fun,q.x))
res.sort(key=lambda t:t[0])
for c,P in res[:5]: print(round(c,3),np.round(P,1))
np.save(path.split('/')[-1]+'.proj.npy',res[0][1])
