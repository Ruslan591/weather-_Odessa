import numpy as np, cv2, sys
from scipy.ndimage import distance_transform_edt
from scipy.optimize import minimize
from skimage.measure import label, regionprops
import fit_proj as F
S=0.25
path=sys.argv[1]
im=cv2.imread(path); small=cv2.resize(im,None,fx=S,fy=S,interpolation=cv2.INTER_AREA)
bgr=small.astype(int)
tint=bgr[...,0]-bgr[...,2]   # B-R: море голубовато-серое (~30), суша нейтральная серая (~0)
sea=(tint>18)
sea=cv2.morphologyEx(sea.astype(np.uint8),cv2.MORPH_CLOSE,np.ones((7,7),np.uint8))
lab=label(sea,connectivity=1); keep=np.zeros(sea.shape,bool)
for r in regionprops(lab):
    if r.area>1500: keep|=lab==r.label
sea=keep
# дырки в море (подписи, станции) заливаем: оставляем только внешние контуры крупных кусков
inv=(~sea).astype(np.uint8); lab2=label(inv,connectivity=1)
for r in regionprops(lab2):
    if r.area<600: sea|=lab2==r.label
# legend/labels box bottom-left and left strip: exclude
h,w=sea.shape
valid=np.ones_like(sea); valid[int(h*0.89):, :int(w*0.17)]=False; valid[:, :int(w*0.012)]=False
k3=np.ones((3,3),np.uint8)
land_like=(~sea)&valid
edge=(cv2.dilate(sea.astype(np.uint8),k3)&cv2.dilate(land_like.astype(np.uint8),k3)).astype(bool)&valid
edge=cv2.morphologyEx(edge.astype(np.uint8),cv2.MORPH_OPEN,np.ones((2,2),np.uint8)).astype(bool)
cv2.imwrite('ana_edge.png',(edge*255).astype(np.uint8))
dt=distance_transform_edt(~edge)
rings=F.load_land()
pts=np.concatenate([r[::2] for r in rings]); pts=pts[(pts[:,1]>20)&(pts[:,1]<78)&(pts[:,0]>-60)&(pts[:,0]<80)]
def cost(P):
    x,y=F.proj(pts[:,0],pts[:,1],P); x=x*S; y=y*S
    ok=(x>3)&(x<w-3)&(y>3)&(y<h-3)
    if ok.sum()<300: return 50
    xi=x[ok].astype(int); yi=y[ok].astype(int)
    d=np.minimum(dt[yi,xi],10)
    return d.mean()+8*(1-ok.mean())*0.2
best=[]
W0=im.shape[1]
for lon0 in range(-30,41,5):
  for k in (3000,3500,4000,4500,5000,5600):
    for x0 in np.linspace(0.1*W0,1.0*W0,7):
      for y0 in np.linspace(-1.2*W0,0.2*W0,10):
        P=np.array([lon0,k,x0,y0],float); best.append((cost(P),tuple(P)))
best.sort(); res=[]
for c,P in best[:15]:
    q=minimize(cost,np.array(P),method='Nelder-Mead',options={'xatol':0.05,'fatol':1e-5,'maxiter':600}); res.append((q.fun,q.x))
res.sort(key=lambda t:t[0])
for c,P in res[:4]: print(round(c,3),np.round(P,1))
np.save('ana.proj.npy',res[0][1])
