#!/usr/bin/env python3
"""Пробник озвучки: один и тот же фрагмент прогноза голосами Silero v4_ru и edge-tts.
Результат публикуется в docs/tts_samples/ (index.html + mp3). В прод-пайплайн не вмешивается."""
import os, sys, re, json, base64, subprocess, time, wave, urllib.request

REPO = "/opt/weather-pipeline/repo"
sys.path.insert(0, os.path.join(REPO, "scripts"))
OUT = "/tmp/tts_samples"
os.makedirs(OUT, exist_ok=True)
API = "https://api.github.com/repos/ruslan591/weather-_Odessa/contents/"
TOKEN = open("/etc/vps-github-bridge/token").read().strip()

import make_blocks_gemini_cloud as m  # preprocess_tts, parse_sections, edge-tts

def pick_text():
    d = json.load(open(os.path.join(REPO, "data", "forecast_analysis_gemini.json"), encoding="utf-8"))
    secs = m.parse_sections(d["text"])
    cands = []
    if isinstance(secs, dict):
        for k, v in secs.items():
            if isinstance(v, str) and len(v) > 250 and "очност" not in k:
                cands.append(v)
    raw = cands[0] if cands else re.sub(r"[#*]+", "", d["text"])
    sents = m.split_sentences(raw)
    out, n = [], 0
    for s in sents:
        out.append(s); n += len(s)
        if n > 650: break
    return " ".join(out)

def to_mp3(wav, mp3):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-c:a", "libmp3lame", "-q:a", "4", mp3], check=True)

def silero_all(text):
    import torch, numpy as np
    torch.set_num_threads(2)
    f = "/tmp/silero_v4_ru.pt"
    if not os.path.isfile(f):
        torch.hub.download_url_to_file("https://models.silero.ai/models/tts/ru/v4_ru.pt", f)
    model = torch.package.PackageImporter(f).load_pickle("tts_models", "model")
    model.to(torch.device("cpu"))
    clean = m.preprocess_tts(text)
    clean = re.sub(r"[^А-Яа-яЁё0-9\s.,!?:;()«»\"%\-—]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    chunks, cur = [], ""
    for s in re.split(r"(?<=[.!?])\s+", clean):
        if len(cur) + len(s) > 700 and cur:
            chunks.append(cur); cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur: chunks.append(cur)
    res = []
    for sp in ["aidar", "baya", "kseniya", "xenia", "eugene"]:
        t0 = time.time()
        parts = []
        for c in chunks:
            a = model.apply_tts(text=c, speaker=sp, sample_rate=48000, put_accent=True, put_yo=True)
            parts.append(a.numpy()); parts.append(np.zeros(int(48000 * 0.3), dtype="float32"))
        pcm = (np.concatenate(parts) * 32767).astype("int16")
        w = f"{OUT}/silero_{sp}.wav"
        with wave.open(w, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(48000); wf.writeframes(pcm.tobytes())
        to_mp3(w, f"{OUT}/silero_{sp}.mp3"); os.remove(w)
        print(f"silero {sp}: {time.time()-t0:.1f}s", flush=True)
        res.append((f"Silero · {sp}", f"silero_{sp}.mp3"))
    return res

def edge_all(text):
    res = []
    for v in ["ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural"]:
        m._selected_voice = v
        p = f"{OUT}/edge_{v.split('-')[2].replace('Neural','').lower()}.mp3"
        m.generate_block_tts(text, p)
        if os.path.exists(p): res.append((f"edge-tts · {v}", os.path.basename(p)))
    return res

def put(path, data):
    url = API + path
    h = {"Authorization": "token " + TOKEN, "Accept": "application/vnd.github+json"}
    sha = None
    try:
        sha = json.load(urllib.request.urlopen(urllib.request.Request(url + "?ref=main", headers=h)))["sha"]
    except Exception:
        pass
    body = {"message": "tts samples: " + path, "content": base64.b64encode(data).decode(), "branch": "main"}
    if sha: body["sha"] = sha
    r = urllib.request.Request(url, data=json.dumps(body).encode(), headers=h, method="PUT")
    urllib.request.urlopen(r).read()

if __name__ == "__main__":
    text = pick_text()
    print("TEXT:", text[:200], flush=True)
    items = silero_all(text) + edge_all(text)
    html = ["<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>",
            "<title>Пробник озвучки</title><body style='font-family:sans-serif;max-width:640px;margin:16px auto;padding:0 12px'>",
            "<h2>Пробник озвучки</h2><p style='color:#555'>" + text + "</p>"]
    for title, fn in items:
        html.append(f"<h4>{title}</h4><audio controls preload=none src='{fn}' style='width:100%'></audio>")
    for title, fn in items:
        put("docs/tts_samples/" + fn, open(f"{OUT}/{fn}", "rb").read())
    put("docs/tts_samples/index.html", "\n".join(html).encode())
    print("DONE", len(items), flush=True)
