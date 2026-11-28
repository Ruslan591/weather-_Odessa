# -*- coding: utf-8 -*-
"""График температуры на 14 дней с разбросом моделей (для страницы «Предварительный прогноз») и хостинг картинки в репозитории.

  python3 weather_tg_chart.py [--host]   тест: рисует по живым данным в /tmp/chart_test.png, с --host кладёт в репозиторий и печатает ссылку
"""
import io
import json
import sys
import urllib.request
import uuid

WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def temp_chart_png(days, daily, split_index):
    """days: список дат; daily: {дата: {tmax: [...], tmin: [...]}} по моделям; split_index: с какого дня «предварительно»."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ok = [d for d in days if daily.get(d, {}).get("tmax") and daily[d].get("tmin")]
    x = [i for i, d in enumerate(days) if d in ok]
    mean = lambda a: sum(a) / len(a)
    hi = [daily[d]["tmax"] for d in ok]
    lo = [daily[d]["tmin"] for d in ok]
    fig, ax = plt.subplots(figsize=(8, 5.0), dpi=120)
    ax.fill_between(x, [min(v) for v in hi], [max(v) for v in hi], color="#f4a261", alpha=0.30, lw=0)
    ax.plot(x, [mean(v) for v in hi], color="#e76f51", lw=3, marker="o", ms=5, label="днём")
    ax.fill_between(x, [min(v) for v in lo], [max(v) for v in lo], color="#8ecae6", alpha=0.45, lw=0)
    ax.plot(x, [mean(v) for v in lo], color="#2a6f97", lw=3, marker="o", ms=5, label="ночью")
    ax.axhline(0, color="#888888", lw=0.9, ls=":")
    if 0 < split_index < len(days):
        ax.axvline(split_index - 0.5, color="#555555", lw=1, ls="--")
        top = ax.get_ylim()[1]
        ax.text(split_index / 2.0 - 0.5, top, "на неделю", ha="center", va="top", fontsize=13, color="#444444")
        ax.text((split_index + len(days)) / 2.0 - 0.5, top, "предварительно", ha="center", va="top", fontsize=13, color="#444444")
    ax.set_xticks(range(len(days)))
    ax.set_xticklabels(["%s\n%d" % (WD[d.weekday()], d.day) for d in days], fontsize=12)
    ax.tick_params(axis="y", labelsize=13)
    ax.set_xlim(-0.5, len(days) - 0.5)
    ax.set_ylabel("°C", fontsize=14)
    ax.set_title("Температура на 14 дней, полоса: разброс моделей", fontsize=15)
    ax.grid(True, color="#dddddd", lw=0.6)
    ax.legend(loc="lower left", fontsize=14, frameon=False)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


REPO = "/opt/weather-pipeline/repo"
RAW = "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/"


def host_in_repo(png, name):
    """Telegraph не принимает анонимную загрузку картинок (400), поэтому PNG кладём в репозиторий (data/charts/<name>.png)
    и отдаём ссылку raw.githubusercontent.com: Telegraph принимает внешний URL в img. Храним последние 8 графиков."""
    import glob
    import os
    import subprocess
    import time
    rel = "data/charts/%s.png" % name
    os.makedirs(os.path.join(REPO, "data", "charts"), exist_ok=True)
    with open(os.path.join(REPO, rel), "wb") as f:
        f.write(png)
    for old in sorted(glob.glob(os.path.join(REPO, "data", "charts", "prelim_*.png")))[:-8]:
        os.remove(old)

    def git(*a):
        return subprocess.run(["git", "-C", REPO] + list(a), capture_output=True, text=True, timeout=90)
    git("add", "-A", "--", "data/charts")
    git("commit", "-q", "-m", "charts: " + name, "--", "data/charts")
    err = ""
    for _ in range(3):
        git("pull", "--rebase", "--autostash", "-q")
        p = git("push", "-q", "origin", "main")
        if p.returncode == 0:
            return RAW + rel
        err = p.stderr[:200]
        time.sleep(4)
    raise RuntimeError("git push: " + err)


def upload_telegraph(png):
    """Загрузка PNG на Telegraph; возвращает полный URL или None."""
    b = uuid.uuid4().hex
    body = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"chart.png\"\r\nContent-Type: image/png\r\n\r\n" % b).encode()
            + png + ("\r\n--%s--\r\n" % b).encode())
    req = urllib.request.Request("https://telegra.ph/upload", data=body, headers={"Content-Type": "multipart/form-data; boundary=" + b})
    with urllib.request.urlopen(req, timeout=40) as r:
        j = json.loads(r.read().decode())
    if isinstance(j, list) and j and j[0].get("src"):
        return "https://telegra.ph" + j[0]["src"]
    raise RuntimeError("telegraph upload: %s" % str(j)[:200])


if __name__ == "__main__":
    import weather_tg_review as rv
    from datetime import datetime, timedelta, timezone
    ln = datetime.now(timezone.utc).astimezone(rv.KYIV)
    daily = rv.fetch_daily(print)
    days = [ln.date() + timedelta(days=i) for i in range(1, 15)]
    png = temp_chart_png(days, daily, 7)
    open("/tmp/chart_test.png", "wb").write(png)
    print("png", len(png), "байт")
    if "--host" in sys.argv:
        try:
            print("URL", host_in_repo(png, "prelim_" + ln.date().isoformat()))
        except Exception as e:
            print("HOST ERR", type(e).__name__, str(e)[:200])
