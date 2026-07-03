import requests, re, json, os
from datetime import datetime, timezone

DATA_FILE = 'data/sst_compare.json'
LAT, LON = 46.44, 30.76

def fetch_openmeteo():
    try:
        r = requests.get(
            f'https://marine-api.open-meteo.com/v1/marine?latitude={LAT}&longitude={LON}&current=sea_surface_temperature&timezone=auto',
            timeout=15)
        return r.json().get('current', {}).get('sea_surface_temperature')
    except Exception as e:
        return f'ERR:{e}'

def fetch_oisst():
    try:
        url = (f'https://coastwatch.pfeg.noaa.gov/erddap/griddap/'
               f'ncdcOisst21NrtAgg_LonPM180.json?sst%5B(last)%5D%5B(0.0)%5D'
               f'%5B({LAT})%5D%5B({LON})%5D')
        r = requests.get(url, timeout=20)
        rows = r.json()['table']['rows']
        return rows[0][-1] if rows else None
    except Exception as e:
        return f'ERR:{e}'

def fetch_seatemp():
    try:
        r = requests.get(
            'https://ukr.seatemperature.net/zaraz/ukraine/odessa-odeska-oblast-ukraine-sea-temperature',
            timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        html = r.text
        m = re.search(r'(\d{1,2}[.,]\d)\s*°C\s*</[^>]+>\s*Сьогодні', html)
        if not m:
            m = re.search(r'сьогодні\s+становить\s*(\d{1,2}[.,]\d)\s*°C', html)
        if not m:
            return f'ERR:pattern_not_found (len={len(html)})'
        return float(m.group(1).replace(',', '.'))
    except Exception as e:
        return f'ERR:{e}'

def main():
    record = {
        'time': datetime.now(timezone.utc).isoformat(),
        'open_meteo': fetch_openmeteo(),
        'oisst_nrt': fetch_oisst(),
        'seatemperature_net': fetch_seatemp(),
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
