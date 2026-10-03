import subprocess,urllib.request,base64,sys,os
os.chdir(os.environ.get('TRIM_DIR','/home/claude/trim')); os.environ['GIT_NO_LAZY_FETCH']='1'
T=os.environ["GH_TOKEN"]
URL="https://github.com/Ruslan591/weather-_Odessa.git/git-receive-pack"
def pkt(b): return b'%04x'%(len(b)+4)+b
# usage: push_pack.py "ref:new:old" ...  (old=0 for create) ; tips given by --tips
cmds=[a.split(':') for a in sys.argv[1:]]
tips=[c[1] for c in cmds]
lst=subprocess.check_output(['git','rev-list']+tips).decode()
pack=subprocess.check_output(['git','pack-objects','--stdout','-q'],input=lst.encode())
print('commits in pack',len(lst.split()),'pack bytes',len(pack))
body=b''
for i,(ref,new,old) in enumerate(cmds):
    old=old if len(old)==40 else '0'*40
    line=('%s %s %s'%(old,new,ref)).encode()
    if i==0: line+=b'\0 report-status side-band-64k object-format=sha1 agent=git/2.43.0'
    body+=pkt(line+b'\n')
body+=b'0000'+pack
req=urllib.request.Request(URL,data=body,method='POST',headers={
 'Authorization':'Basic '+base64.b64encode(('x-access-token:'+T).encode()).decode(),
 'Content-Type':'application/x-git-receive-pack-request','Accept':'application/x-git-receive-pack-result'})
try:
    r=urllib.request.urlopen(req,timeout=250); data=r.read()
except urllib.error.HTTPError as e:
    print('HTTP',e.code,e.read()[:500]); sys.exit(1)
print('response:',data.decode('utf-8','replace').replace('\x01','').replace('\x02','')[:700])
