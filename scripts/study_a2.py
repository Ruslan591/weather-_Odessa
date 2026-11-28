import os,json,time
P="/opt/trading-bot/positions_regr/"
for f in sorted(os.listdir(P)):
    s=os.stat(P+f); print(f,s.st_size,time.strftime("%m-%d %H:%M",time.gmtime(s.st_mtime)))
