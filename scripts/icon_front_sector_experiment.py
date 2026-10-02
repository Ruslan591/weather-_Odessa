#!/usr/bin/env python3
"""Офлайн-эксперимент (НЕ боевой код): секторная схема фронтов от центра L.

Идея Ruslan (схема норвежской модели): вокруг центра циклона фронты — границы тёплого сектора и идут по
ложбинам изобар. Здесь только смотрим, видны ли ложбины (азимутальные минимумы давления) и тёплый сектор
(азимутальный максимум θe850) вокруг найденных L, и как они соотносятся с текущими линиями фронтов.

python3 scripts/icon_front_sector_experiment.py <case.npz> <outdir>
Для каждого L: <outdir>/L<n>.jpg (слева карта ±900 км, справа развёртка «азимут–радиус»).
"""
import sys, os, importlib.util
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_filter, map_coordinates

REPO = "/opt/weather-pipeline/repo"
spec = importlib.util.spec_from_file_location("vf", REPO + "/scripts/icon_front_very_far_snapshot.py")
vf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vf)

case, outdir = sys.argv[1], sys.argv[2]
os.makedirs(outdir, exist_ok=True)
fields, lats, lons, run_dt, lead = vf.load_testcase(case)
dlat, dlon = lats[1] - lats[0], lons[1] - lons[0]
centers = vf.find_pressure_centers(fields["pmsl"], fields.get("hsurf"), lats, lons)
def _inside(c, margin_km=900.0):
    dl = margin_km / 111.32
    dlo = dl / np.cos(np.radians(c[0]))
    return (lats.min() + dl <= c[0] <= lats.max() - dl) and (lons.min() + dlo <= c[1] <= lons.max() - dlo)
_all_L = sorted([c for c in centers if c[2] == "L"], key=lambda c: c[3])
Ls = [c for c in _all_L if _inside(c)]
print("L у края области (пропущены):", [(round(c[0], 1), round(c[1], 1), round(c[3], 1)) for c in _all_L if not _inside(c)])
print("run", run_dt, "lead", lead, "| центры:", [(round(c[0], 1), round(c[1], 1), c[2], round(c[3], 1)) for c in centers])

hs = fields.get("hsurf")
p0 = fields["pmsl"]
if hs is not None:
    terr = gaussian_filter(hs, 2.0) > vf.TERRAIN_MASK_M
    if terr.any():
        f = vf._fill_masked_laplace(p0, terr)
        if f is not None:
            p0 = f
P = gaussian_filter(p0, 3.0)
TH = gaussian_filter(vf.theta_e_bolton(fields["t850"], fields["relhum850"], 850.0), 4.0)
fronts, _ = vf.compute_fronts(fields, lats, lons, centers=centers)

def sample(F, lat0, lon0, r_km, phi):
    lat = lat0 + r_km * np.sin(phi) / 111.32
    lon = lon0 + r_km * np.cos(phi) / (111.32 * np.cos(np.radians((lat0 + lat) / 2)))
    return map_coordinates(F, [(lat - lats[0]) / dlat, (lon - lons[0]) / dlon], order=1, mode="nearest")

COMP = ["В", "СВ", "С", "СЗ", "З", "ЮЗ", "Ю", "ЮВ"]
def compass(phi_deg):  # phi: математический угол от востока против часовой
    return COMP[int(((phi_deg + 22.5) % 360) // 45)]

R = np.arange(50, 1001, 25.0)
PHI_DEG = np.arange(0, 360, 3.0)
PHI = np.radians(PHI_DEG)

for n, (lat0, lon0, kind, pc) in enumerate(Ls[:4]):
    Zp = np.array([sample(P, lat0, lon0, r, PHI) for r in R])
    Zt = np.array([sample(TH, lat0, lon0, r, PHI) for r in R])
    Ap = Zp - Zp.mean(axis=1, keepdims=True)
    At = Zt - Zt.mean(axis=1, keepdims=True)
    print(f"\nL{n}: {lat0:.1f}N {lon0:.1f}E {pc:.1f} гПа")
    for r in (200, 400, 600, 800):
        row = Ap[int(np.argmin(np.abs(R - r)))]
        spec_ = np.fft.rfft(row); spec_[1] = 0
        a2 = np.fft.irfft(spec_, n=len(row))
        mins = [i for i in range(len(a2)) if a2[i] < a2[i - 1] and a2[i] <= a2[(i + 1) % len(a2)] and a2[i] < -0.4]
        trow = At[int(np.argmin(np.abs(R - r)))]
        imax = int(np.argmax(trow))
        print(f"  r={r}км: ложбины(азимут,гПа) {[(compass(PHI_DEG[i]), int(PHI_DEG[i]), round(float(a2[i]), 1)) for i in mins]}; "
              f"θe-макс {compass(PHI_DEG[imax])} {int(PHI_DEG[imax])}° (+{trow[imax]:.1f} К, размах {trow.max()-trow.min():.1f})")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6.4), gridspec_kw={"width_ratios": [1, 1.1]})
    dl = 900 / 111.32; dlo = dl / np.cos(np.radians(lat0))
    w, e, s, nn = lon0 - dlo, lon0 + dlo, lat0 - dl, lat0 + dl
    li = (lats >= s) & (lats <= nn); lj = (lons >= w) & (lons <= e)
    th_c = TH[np.ix_(li, lj)]; p_c = P[np.ix_(li, lj)]
    ax1.pcolormesh(lons[lj], lats[li], th_c, cmap="RdBu_r", shading="auto", alpha=0.55)
    cs = ax1.contour(lons[lj], lats[li], p_c, levels=np.arange(940, 1060, 2), colors="k", linewidths=0.8)
    ax1.clabel(cs, fmt="%d", fontsize=7)
    ck = {"cold": "#0030ff", "warm": "#e00000", "stat": "#a000c0"}
    for sg in fronts:
        xy = sg["xy"]; kd = sg["kind"]
        for k in ("cold", "warm", "stat"):
            m = np.array([x == k for x in kd])
            ax1.scatter(xy[m, 0], xy[m, 1], s=7, c=ck[k], zorder=5)
    ax1.plot(lon0, lat0, "k*", ms=16, zorder=6)
    for rr in (300, 600, 900):
        t = np.linspace(0, 2 * np.pi, 200)
        ax1.plot(lon0 + rr * np.cos(t) / (111.32 * np.cos(np.radians(lat0))), lat0 + rr * np.sin(t) / 111.32, "g:", lw=0.8)
    ax1.set_xlim(w, e); ax1.set_ylim(s, nn); ax1.set_title(f"L{n} {pc:.0f} гПа: θe850 (красное=тепло), изобары, текущие фронты")
    ax2.imshow(Ap, origin="lower", aspect="auto", cmap="PuOr_r", extent=[0, 360, R[0], R[-1]],
               vmin=-max(2, np.abs(Ap).max()), vmax=max(2, np.abs(Ap).max()))
    c2 = ax2.contour(PHI_DEG, R, At, levels=[-2, 0, 2, 4, 6], colors=["b", "gray", "orange", "r", "darkred"], linewidths=1.2)
    ax2.clabel(c2, fmt="%d", fontsize=7)
    ax2.set_xticks([0, 45, 90, 135, 180, 225, 270, 315, 360]); ax2.set_xticklabels(["В", "СВ", "С", "СЗ", "З", "ЮЗ", "Ю", "ЮВ", "В"])
    ax2.set_xlabel("азимут от центра (против часовой)"); ax2.set_ylabel("радиус, км")
    ax2.set_title("аномалия давления по кругу (фиол=ниже, оранж=выше) и θe (линии)")
    fig.tight_layout()
    fig.savefig(f"{outdir}/L{n}.jpg", dpi=70, pil_kwargs={"quality": 75})
    plt.close(fig)
print("done")
