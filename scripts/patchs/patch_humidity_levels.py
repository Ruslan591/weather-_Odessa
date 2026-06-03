FILE = 'js/fc-ensemble.js'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

# 1. Добавить поля в HOURLY_PARAMS
OLD = '''        "geopotential_height_150hPa,geopotential_height_100hPa,geopotential_height_50hPa,geopotential_height_30hPa,geopotential_height_10hPa";'''
NEW = '''        "geopotential_height_150hPa,geopotential_height_100hPa,geopotential_height_50hPa,geopotential_height_30hPa,geopotential_height_10hPa," +
        "relative_humidity_850hPa,relative_humidity_700hPa,relative_humidity_500hPa," +
        "cloudcover_850hPa,cloudcover_700hPa,cloudcover_500hPa,cloudcover_250hPa";'''
assert OLD in src, "OLD HOURLY_PARAMS not found"
src = src.replace(OLD, NEW, 1)

# 2. Добавить поля в parseHourly (после geopotential_height_10hPa строки)
OLD2 = '''            geopotential_height_10hPa:      h.geopotential_height_10hPa      ? h.geopotential_height_10hPa[i]      : null,
        };'''
NEW2 = '''            geopotential_height_10hPa:      h.geopotential_height_10hPa      ? h.geopotential_height_10hPa[i]      : null,
            relative_humidity_850hPa:       h.relative_humidity_850hPa       ? h.relative_humidity_850hPa[i]       : null,
            relative_humidity_700hPa:       h.relative_humidity_700hPa       ? h.relative_humidity_700hPa[i]       : null,
            relative_humidity_500hPa:       h.relative_humidity_500hPa       ? h.relative_humidity_500hPa[i]       : null,
            cloudcover_850hPa:              h.cloudcover_850hPa              ? h.cloudcover_850hPa[i]              : null,
            cloudcover_700hPa:              h.cloudcover_700hPa              ? h.cloudcover_700hPa[i]              : null,
            cloudcover_500hPa:              h.cloudcover_500hPa              ? h.cloudcover_500hPa[i]              : null,
            cloudcover_250hPa:              h.cloudcover_250hPa              ? h.cloudcover_250hPa[i]              : null,
        };'''
assert OLD2 in src, "OLD2 parseHourly not found"
src = src.replace(OLD2, NEW2, 1)

# 3. Добавить поля в numericFields (mergeEnsemble)
OLD3 = '''        "geopotential_height_150hPa","geopotential_height_100hPa","geopotential_height_50hPa",
        "geopotential_height_30hPa","geopotential_height_10hPa"
    ];'''
NEW3 = '''        "geopotential_height_150hPa","geopotential_height_100hPa","geopotential_height_50hPa",
        "geopotential_height_30hPa","geopotential_height_10hPa",
        "relative_humidity_850hPa","relative_humidity_700hPa","relative_humidity_500hPa",
        "cloudcover_850hPa","cloudcover_700hPa","cloudcover_500hPa","cloudcover_250hPa"
    ];'''
assert OLD3 in src, "OLD3 numericFields not found"
src = src.replace(OLD3, NEW3, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")