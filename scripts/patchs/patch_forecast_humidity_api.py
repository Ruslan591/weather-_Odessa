FILE = 'js/fc-forecast.js'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

# Добавить поля в API-строку (конец параметров перед &models=)
OLD = '''vertical_velocity_500hPa,vertical_velocity_700hPa,vertical_velocity_850hPa&models='''
NEW = '''vertical_velocity_500hPa,vertical_velocity_700hPa,vertical_velocity_850hPa,relative_humidity_850hPa,relative_humidity_700hPa,relative_humidity_500hPa,cloudcover_850hPa,cloudcover_700hPa,cloudcover_500hPa,cloudcover_250hPa&models='''
assert OLD in src, "OLD API not found"
src = src.replace(OLD, NEW, 1)

# Добавить поля в парсинг часов (после vertical_velocity_850hPa)
OLD2 = '''        vertical_velocity_850hPa:    h.vertical_velocity_850hPa?.[i]    ?? null,
    }));'''
NEW2 = '''        vertical_velocity_850hPa:    h.vertical_velocity_850hPa?.[i]    ?? null,
        relative_humidity_850hPa:    h.relative_humidity_850hPa?.[i]    ?? null,
        relative_humidity_700hPa:    h.relative_humidity_700hPa?.[i]    ?? null,
        relative_humidity_500hPa:    h.relative_humidity_500hPa?.[i]    ?? null,
        cloudcover_850hPa:           h.cloudcover_850hPa?.[i]           ?? null,
        cloudcover_700hPa:           h.cloudcover_700hPa?.[i]           ?? null,
        cloudcover_500hPa:           h.cloudcover_500hPa?.[i]           ?? null,
        cloudcover_250hPa:           h.cloudcover_250hPa?.[i]           ?? null,
    }));'''
assert OLD2 in src, "OLD2 parse not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")