"""Офлайн-эксперимент: секторная схема фронтов от центра циклона (идея Ruslan, схема норвежской модели).
Ничего не публикует. Вход — замороженный снимок (npz из ICON_FRONT_SAVE_TESTCASE)."""
import sys, math
import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates

sys.path.insert(0, "/tmp/sc")
import icon_front_very_far_snapshot as vf

KM_LAT = 111.32


def prep(path):
    fields, lats, lons, run_dt, lead = vf.load_testcase(path)
    terr = gaussian_filter(fields["hsurf"], 2.0) > vf.TERRAIN_MASK_M
    p = vf._fill_masked_laplace(fields["pmsl"], terr)
    the = vf.theta_e_bolton(fields["t850"], fields["relhum850"], 850.0)
    return fields, lats, lons, p, the, run_dt, lead


def ring_sampler(field, lats, lons, lat0, lon0):
    dlat = lats[1] - lats[0]; dlon = lons[1] - lons[0]

    def sample(r_km, th_deg):
        th = np.radians(th_deg)  # математический угол: 0=восток, 90=север
        dy = r_km * np.sin(th) / KM_LAT
        la = lat0 + dy
        dx = r_km * np.cos(th) / (KM_LAT * np.cos(np.radians((la + lat0) / 2)))
        lo = lon0 + dx
        ii = (la - lats[0]) / dlat; jj = (lo - lons[0]) / dlon
        return map_coordinates(field, [ii, jj], order=1, mode="nearest")
    return sample


def dog(p, s1=4.0, s2=16.0):
    return gaussian_filter(p, s1) - gaussian_filter(p, s2)


def azimuth_troughs(D, lats, lons, lat0, lon0, radii, step_deg=5, thr=0.4, smooth_deg=10):
    """Для каждого радиуса — азимуты локальных минимумов D (оси ложбин) и их глубина."""
    th = np.arange(0, 360, step_deg)
    samp = ring_sampler(D, lats, lons, lat0, lon0)
    out = {}
    for r in radii:
        v = samp(np.full_like(th, r, dtype=float), th.astype(float))
        k = max(1, int(round(smooth_deg / step_deg)))
        vs = np.convolve(np.r_[v[-k:], v, v[:k]], np.ones(2 * k + 1) / (2 * k + 1), mode="same")[k:-k]
        mins = [i for i in range(len(vs)) if vs[i] < vs[i - 1] and vs[i] <= vs[(i + 1) % len(vs)] and vs[i] < -thr]
        out[r] = [(float(th[i]), float(vs[i])) for i in mins]
    return th, out
