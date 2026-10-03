import json, numpy as np
from scipy.spatial import cKDTree
BBOX=(-10.0,35.0,32.0,60.0); R_E=6371.0
def xyz(lon,lat):
    lo,la=np.radians(lon),np.radians(lat); return R_E*np.stack([np.cos(la)*np.cos(lo),np.cos(la)*np.sin(lo),np.sin(la)],-1)
def sample(path,step_km=20):
    d=json.load(open(path)); pts=[]; kd=[]
    for f in d["features"]:
        if f["geometry"]["type"]!="LineString": continue
        c=np.array(f["geometry"]["coordinates"]); 
        for a,b in zip(c[:-1],c[1:]):
            n=max(1,int(np.linalg.norm(xyz(*a)-xyz(*b))//step_km))
            for t in np.linspace(0,1,n,endpoint=False): pts.append(a+(b-a)*t); kd.append(f["properties"]["kind"])
    pts=np.array(pts); kd=np.array(kd); m=(pts[:,0]>=BBOX[0])&(pts[:,0]<=BBOX[2])&(pts[:,1]>=BBOX[1])&(pts[:,1]<=BBOX[3])
    return pts[m],kd[m]
def compare(our,dwd,Rs=(100,200,300)):
    po,ko=sample(our); pd_,kd=sample(dwd); to=cKDTree(xyz(po[:,0],po[:,1])); td=cKDTree(xyz(pd_[:,0],pd_[:,1]))
    d_od,i_od=td.query(xyz(po[:,0],po[:,1])); d_do,i_do=to.query(xyz(pd_[:,0],pd_[:,1]))
    res={"our_km":len(po)*20,"dwd_km":len(pd_)*20}
    for R in Rs: res["our_near_dwd_%d"%R]=round(float((d_od<=R).mean()),2); res["dwd_near_our_%d"%R]=round(float((d_do<=R).mean()),2)
    res["median_dist_our_to_dwd"]=round(float(np.median(d_od))); res["median_dist_dwd_to_our"]=round(float(np.median(d_do)))
    near=d_od<=300; res["type_pairs_within300"]={}
    for a,b in zip(ko[near],kd[i_od[near]]): res["type_pairs_within300"][a+"->"+b]=res["type_pairs_within300"].get(a+"->"+b,0)+1
    return res,(po,ko,d_od),(pd_,kd,d_do)
if __name__=="__main__":
    for t in ("12","18"):
        r,_,_=compare("our%s.json"%t,"dwd%s.json"%t); print(t+"Z",json.dumps(r,ensure_ascii=False))
