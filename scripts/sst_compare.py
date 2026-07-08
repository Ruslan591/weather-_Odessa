import requests, json, os
from datetime import datetime, timezone

DATA_FILE = 'data/sst_compare.json'
LAT, LON = 46.35, 30.90  # та же точка, что и loadMarine() в pws_page.js

def fetch_openmeteo():
    try:
        r = requests.get(
            f'https://marine-api.open-meteo.com/v1/marine?latitude={LAT}&longitude={LON}&current=sea_surface_temperature&timezone=auto',
            timeout=15)
        return r.json().get('current', {}).get('sea_surface_temperature')
    except Exception as e:
        return f'ERR:{e}'

def main():
    record = {
        'time': datetime.now(timezone.utc).isoformat(),
        'open_meteo': fetch_openmeteo(),
    }
    data = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    data.append(record)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(record)

if __name__ == '__main__':
    main()
