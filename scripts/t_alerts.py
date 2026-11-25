import weather_tg_ai as ai, weather_tg_channel as ch
ai.budget(200)
for g in ("7,2","9,1","12,4"):
    al="💨 <b>Порывы ветра до %s м/с</b>\nпос. Котовского %s; Аркадия 8,0 (м/с).\nВетер З, 6 м/с.\n🕐 12:20" % (g,g)
    print("GUST",g,"->",ai.alert_line(al,ch.log,[]))
