FILE = 'scripts/generate_ai_analysis.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()
OLD = '''    WS200 = col("windspeed_200hPa");  WD200 = col("winddirection_200hPa")'''
NEW = '''    WS200 = col("windspeed_200hPa");  WD200 = col("winddirection_200hPa")
    WS100 = col("windspeed_100hPa");  WD100 = col("winddirection_100hPa")
    WS50  = col("windspeed_50hPa");   WD50  = col("winddirection_50hPa")'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
OLD2 = '''        ws300m,wd300m=wmd(WS300,WD300); ws250m,wd250m=wmd(WS250,WD250)
        ws200m,wd200m=wmd(WS200,WD200)'''
NEW2 = '''        ws300m,wd300m=wmd(WS300,WD300); ws250m,wd250m=wmd(WS250,WD250)
        ws200m,wd200m=wmd(WS200,WD200)
        ws100m,wd100m=wmd(WS100,WD100); ws50m,wd50m=wmd(WS50,WD50)'''
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)
OLD3 = '''                "300":{"s":ws300m,"d":wd300m},"250":{"s":ws250m,"d":wd250m},
                "200":{"s":ws200m,"d":wd200m},
            },'''
NEW3 = '''                "300":{"s":ws300m,"d":wd300m},"250":{"s":ws250m,"d":wd250m},
                "200":{"s":ws200m,"d":wd200m},
                "100":{"s":ws100m,"d":wd100m},"50":{"s":ws50m,"d":wd50m},
            },'''
assert OLD3 in src, "OLD3 not found"
src = src.replace(OLD3, NEW3, 1)
with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK2")
