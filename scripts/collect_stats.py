"""
Сборщик CSV-статистики kt_oc в один файл.
Запуск: cd /storage/emulated/0/Documents/weather
python3 scripts/collect_stats.py IODESS16
"""
import os, sys, glob

def main():
    station = sys.argv[1] if len(sys.argv) > 1 else None

    if station:
        base = f"data/pws/stations/{station}"
        out  = f"{base}/kt_oc_stats_all_{station}.txt"
        label_prefix = f"STATION: {station}"
    else:
        base = "data/pws/combined"
        out  = f"{base}/kt_oc_stats_all_combined.txt"
        label_prefix = "COMBINED"

    sections = [
        ("OVERALL",  [f"{base}/kt_oc_table_stats.csv"]),
        ("SEASONAL", sorted(glob.glob(f"{base}/seasonal/kt_oc_table_*_stats.csv"))),
        ("MONTHLY",  sorted(glob.glob(f"{base}/monthly/kt_oc_table_*_stats.csv"))),
        ("YEARLY",   sorted(glob.glob(f"{base}/yearly/kt_oc_table_*_stats.csv"))),
    ]

    with open(out, "w") as out_f:
        out_f.write(f"{label_prefix}\n\n")
        for section, files in sections:
            for path in files:
                if not os.path.exists(path):
                    continue
                label = os.path.basename(path).replace("kt_oc_table_", "").replace("_stats.csv", "").upper()
                header = f"=== {section} {label} ===" if label else f"=== {section} ==="
                out_f.write(header + "\n")
                with open(path) as f:
                    out_f.write(f.read())
                out_f.write("\n")

    print(f"Сохранено: {out}")

if __name__ == "__main__":
    main()
