def show(path,a,b):
    L=open(path,encoding="utf-8").read().split("\n")
    for i in range(a-1,min(b,len(L))): print("%d:%s"%(i+1,ascii(L[i])))
show("/opt/trading-bot/live/live_web.py",125,235)
print("=====HTML")
show("/opt/trading-bot/live/index.html",404,470)
