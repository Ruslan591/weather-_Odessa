# Исправляет cloudcover_ → cloud_cover_, добавляет уровни 925/300 для влажности и облачности

# ── fc-ensemble.js ──────────────────────────────────────────────────────────
FILE = 'js/fc-ensemble.js'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

# 1. HOURLY_PARAMS: исправить cloudcover_ → cloud_cover_, добавить уровни
OLD = (
    '        "relative_humidity_850hPa,relative_humidity_700hPa,relative_humidity_500hPa," +\n'
    '        "cloudcover_850hPa,cloudcover_700hPa,cloudcover_500hPa,cloudcover_250hPa";'
)
NEW = (
    '        "relative_humidity_925hPa,relative_humidity_850hPa,relative_humidity_700hPa,relative_humidity_500hPa,relative_humidity_300hPa," +\n'
    '        "cloud_cover_925hPa,cloud_cover_850hPa,cloud_cover_700hPa,cloud_cover_500hPa,cloud_cover_300hPa";'
)
assert OLD in src, "OLD HOURLY_PARAMS not found"
src = src.replace(OLD, NEW, 1)

# 2. parseHourly: исправить и расширить
OLD2 = (
    '            relative_humidity_850hPa:       h.relative_humidity_850hPa       ? h.relative_humidity_850hPa[i]       : null,\n'
    '            relative_humidity_700hPa:       h.relative_humidity_700hPa       ? h.relative_humidity_700hPa[i]       : null,\n'
    '            relative_humidity_500hPa:       h.relative_humidity_500hPa       ? h.relative_humidity_500hPa[i]       : null,\n'
    '            cloudcover_850hPa:              h.cloudcover_850hPa              ? h.cloudcover_850hPa[i]              : null,\n'
    '            cloudcover_700hPa:              h.cloudcover_700hPa              ? h.cloudcover_700hPa[i]              : null,\n'
    '            cloudcover_500hPa:              h.cloudcover_500hPa              ? h.cloudcover_500hPa[i]              : null,\n'
    '            cloudcover_250hPa:              h.cloudcover_250hPa              ? h.cloudcover_250hPa[i]              : null,'
)
NEW2 = (
    '            relative_humidity_925hPa:       h.relative_humidity_925hPa       ? h.relative_humidity_925hPa[i]       : null,\n'
    '            relative_humidity_850hPa:       h.relative_humidity_850hPa       ? h.relative_humidity_850hPa[i]       : null,\n'
    '            relative_humidity_700hPa:       h.relative_humidity_700hPa       ? h.relative_humidity_700hPa[i]       : null,\n'
    '            relative_humidity_500hPa:       h.relative_humidity_500hPa       ? h.relative_humidity_500hPa[i]       : null,\n'
    '            relative_humidity_300hPa:       h.relative_humidity_300hPa       ? h.relative_humidity_300hPa[i]       : null,\n'
    '            cloud_cover_925hPa:             h.cloud_cover_925hPa             ? h.cloud_cover_925hPa[i]             : null,\n'
    '            cloud_cover_850hPa:             h.cloud_cover_850hPa             ? h.cloud_cover_850hPa[i]             : null,\n'
    '            cloud_cover_700hPa:             h.cloud_cover_700hPa             ? h.cloud_cover_700hPa[i]             : null,\n'
    '            cloud_cover_500hPa:             h.cloud_cover_500hPa             ? h.cloud_cover_500hPa[i]             : null,\n'
    '            cloud_cover_300hPa:             h.cloud_cover_300hPa             ? h.cloud_cover_300hPa[i]             : null,'
)
assert OLD2 in src, "OLD2 parseHourly not found"
src = src.replace(OLD2, NEW2, 1)

# 3. numericFields в mergeEnsemble
OLD3 = (
    '        "relative_humidity_850hPa","relative_humidity_700hPa","relative_humidity_500hPa",\n'
    '        "cloudcover_850hPa","cloudcover_700hPa","cloudcover_500hPa","cloudcover_250hPa"\n'
    '    ];'
)
NEW3 = (
    '        "relative_humidity_925hPa","relative_humidity_850hPa","relative_humidity_700hPa","relative_humidity_500hPa","relative_humidity_300hPa",\n'
    '        "cloud_cover_925hPa","cloud_cover_850hPa","cloud_cover_700hPa","cloud_cover_500hPa","cloud_cover_300hPa"\n'
    '    ];'
)
assert OLD3 in src, "OLD3 numericFields not found"
src = src.replace(OLD3, NEW3, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("fc-ensemble.js OK")

# ── fc-forecast.js ──────────────────────────────────────────────────────────
FILE2 = 'js/fc-forecast.js'
with open(FILE2, 'r', encoding='utf-8') as f: src2 = f.read()

# 4. API строка: исправить cloudcover_ → cloud_cover_, добавить уровни
OLD4 = 'vertical_velocity_500hPa,vertical_velocity_700hPa,vertical_velocity_850hPa,relative_humidity_850hPa,relative_humidity_700hPa,relative_humidity_500hPa,cloudcover_850hPa,cloudcover_700hPa,cloudcover_500hPa,cloudcover_250hPa&models='
NEW4 = 'vertical_velocity_500hPa,vertical_velocity_700hPa,vertical_velocity_850hPa,relative_humidity_925hPa,relative_humidity_850hPa,relative_humidity_700hPa,relative_humidity_500hPa,relative_humidity_300hPa,cloud_cover_925hPa,cloud_cover_850hPa,cloud_cover_700hPa,cloud_cover_500hPa,cloud_cover_300hPa&models='
assert OLD4 in src2, "OLD4 API not found"
src2 = src2.replace(OLD4, NEW4, 1)

# 5. Парсинг часов: исправить и расширить
OLD5 = (
    '        relative_humidity_850hPa:    h.relative_humidity_850hPa?.[i]    ?? null,\n'
    '        relative_humidity_700hPa:    h.relative_humidity_700hPa?.[i]    ?? null,\n'
    '        relative_humidity_500hPa:    h.relative_humidity_500hPa?.[i]    ?? null,\n'
    '        cloudcover_850hPa:           h.cloudcover_850hPa?.[i]           ?? null,\n'
    '        cloudcover_700hPa:           h.cloudcover_700hPa?.[i]           ?? null,\n'
    '        cloudcover_500hPa:           h.cloudcover_500hPa?.[i]           ?? null,\n'
    '        cloudcover_250hPa:           h.cloudcover_250hPa?.[i]           ?? null,'
)
NEW5 = (
    '        relative_humidity_925hPa:    h.relative_humidity_925hPa?.[i]    ?? null,\n'
    '        relative_humidity_850hPa:    h.relative_humidity_850hPa?.[i]    ?? null,\n'
    '        relative_humidity_700hPa:    h.relative_humidity_700hPa?.[i]    ?? null,\n'
    '        relative_humidity_500hPa:    h.relative_humidity_500hPa?.[i]    ?? null,\n'
    '        relative_humidity_300hPa:    h.relative_humidity_300hPa?.[i]    ?? null,\n'
    '        cloud_cover_925hPa:          h.cloud_cover_925hPa?.[i]          ?? null,\n'
    '        cloud_cover_850hPa:          h.cloud_cover_850hPa?.[i]          ?? null,\n'
    '        cloud_cover_700hPa:          h.cloud_cover_700hPa?.[i]          ?? null,\n'
    '        cloud_cover_500hPa:          h.cloud_cover_500hPa?.[i]          ?? null,\n'
    '        cloud_cover_300hPa:          h.cloud_cover_300hPa?.[i]          ?? null,'
)
assert OLD5 in src2, "OLD5 parse not found"
src2 = src2.replace(OLD5, NEW5, 1)

with open(FILE2, 'w', encoding='utf-8') as f: f.write(src2)
print("fc-forecast.js OK")