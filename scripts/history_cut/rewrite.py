import subprocess,zlib,hashlib,os,json,sys
os.chdir(os.environ.get('TRIM_DIR','/home/claude/trim'))
CUT=sys.argv[1]  # ISO date, first commit with committer date >= CUT becomes root
def sh(*a): return subprocess.check_output(a).decode().strip()
tip=sh('git','rev-parse','origin/main')
out=subprocess.check_output(['git','log','--reverse','--topo-order','--format=%H %cI',tip]).decode().split('\n')
revs=[l.split(' ')[0] for l in out if l]
root=None
for l in out:
    if not l: continue
    h,d=l.split(' ')
    from datetime import datetime
    if datetime.fromisoformat(d).timestamp()>=datetime.fromisoformat(CUT).timestamp(): root=h;break
# keep only commits that descend from root (linear history expected)
keep=sh('git','rev-list','--reverse','--topo-order',tip,'--not',root+'^@').split('\n') if False else None
anc=set(sh('git','rev-list',tip,'--not',root+'^@').split('\n')) if sh('git','rev-list','--max-parents=0',root) != root else set(sh('git','rev-list',tip).split('\n'))
order=[r for r in revs if r in anc]
print('root',root,'commits kept',len(order))
mp={}
bp=subprocess.Popen(['git','cat-file','--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
def batch(h):
    bp.stdin.write((h+'\n').encode()); bp.stdin.flush()
    hd=bp.stdout.readline().split(); n=int(hd[2]); d=bp.stdout.read(n); bp.stdout.read(1); return d
def rewrite(h,parents_map):
    raw=batch(h)
    head,_,msg=raw.partition(b'\n\n')
    lines=head.split(b'\n'); out=[];skip=False
    for ln in lines:
        if skip:
            if ln.startswith(b' '): continue
            skip=False
        if ln.startswith(b'gpgsig'): skip=True; continue
        if ln.startswith(b'parent '):
            p=ln[7:].decode()
            if p in parents_map: out.append(b'parent '+parents_map[p].encode())
            continue
        out.append(ln)
    data=b'\n'.join(out)+b'\n\n'+msg
    obj=b'commit %d\0'%len(data)+data
    sha=hashlib.sha1(obj).hexdigest()
    d='.git/objects/'+sha[:2]; os.makedirs(d,exist_ok=True)
    p=d+'/'+sha[2:]
    if not os.path.exists(p): open(p,'wb').write(zlib.compress(obj,1))
    return sha
for h in order: mp[h]=rewrite(h,mp)
newtip=mp[tip]
sh('git','update-ref','refs/heads/trim-new',newtip)
# exp branch: commits not in main
ex=sh('git','rev-parse','origin/exp-case-oct1')
extra=sh('git','rev-list','--reverse','--topo-order',ex,'--not',tip).split('\n')
extra=[e for e in extra if e]
em={}; 
for h in extra: em[h]=rewrite(h,{**mp,**em})
sh('git','update-ref','refs/heads/exp-new',em[ex])
json.dump({'root':root,'tip':tip,'newtip':newtip,'exp_old':ex,'exp_new':em[ex],'map':mp},open(os.environ.get('MAP_JSON','/home/claude/map.json'),'w'))
print('old tip',tip[:10],'-> new tip',newtip[:10]); print('exp',ex[:10],'->',em[ex][:10],'extra commits',len(extra))
