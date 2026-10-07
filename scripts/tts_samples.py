#!/usr/bin/env python3
"""Пробник озвучки: один фрагмент прогноза голосами Silero v4_ru и edge-tts.
Режимы (argv[1]):
  prep     (root)    — выбрать и подготовить текст -> /tmp/tts_in/
  silero   (sandbox) — nobody + без сети: Silero -> /tmp/tts_samples/*.mp3
                       (модель .pt — pickle из неофициального зеркала, поэтому изолируем)
  publish  (root)    — edge-tts + выгрузка в docs/tts_samples/ (index.html + mp3)
В прод-пайплайн не вмешивается."""
import os, sys, re, json, base64, subprocess, time, wave, urllib.request

REPO = "/opt/weather-pipeline/repo"
IN = "/tmp/tts_in"
OUT = "/tmp/tts_samples"
MODEL = "/tmp/silero_v4_ru.pt"
SILERO_VOICES = ["aidar", "baya", "kseniya", "xenia", "eugene"]
API = "https://api.github.com/repos/ruslan591/weather-_Odessa/contents/"

def mk():
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import make_blocks_gemini_cloud as m
    return m

def to_mp3(wav, mp3):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-c:a", "libmp3lame", "-q:a", "4", mp3], check=True)

def prep():
    m = mk()
    d = json.load(open(os.path.join(REPO, "data", "forecast_analysis_gemini.json"), encoding="utf-8"))
    secs = m.parse_sections(d["text"])
    cands = [v for k, v in secs.items() if isinstance(v, str) and len(v) > 250 and "очност" not in k] if isinstance(secs, dict) else []
    raw = cands[0] if cands else re.sub(r"[#*]+", "", d["text"])
    out, n = [], 0
    for s in m.split_sentences(raw):
        out.append(s); n += len(s)
        if n > 650: break
    text = re.sub(r"[#*]+", "", " ".join(out)).strip()
    clean = m.preprocess_tts(text)
    clean = re.sub(r"[^А-Яа-яЁё0-9\s.,!?:;()«»\"%\-—]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    os.makedirs(IN, exist_ok=True)
    open(f"{IN}/raw.txt", "w", encoding="utf-8").write(text)
    open(f"{IN}/clean.txt", "w", encoding="utf-8").write(clean)
    print("RAW:", text[:160]); print("CLEAN:", clean[:160], flush=True)

def silero():
    import torch, numpy as np
    torch.set_num_threads(2)
    clean = open(f"{IN}/clean.txt", encoding="utf-8").read()
    model = torch.package.PackageImporter(MODEL).load_pickle("tts_models", "model")
    model.to(torch.device("cpu"))
    chunks, cur = [], ""
    for s in re.split(r"(?<=[.!?])\s+", clean):
        if len(cur) + len(s) > 700 and cur:
            chunks.append(cur); cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur: chunks.append(cur)
    done = []
    for sp in SILERO_VOICES:
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
        done.append(sp)
        print(f"silero {sp}: {time.time()-t0:.1f}s", flush=True)

def put(path, data, token):
    url = API + path
    h = {"Authorization": "token " + token, "Accept": "application/vnd.github+json"}
    sha = None
    try:
        sha = json.load(urllib.request.urlopen(urllib.request.Request(url + "?ref=main", headers=h)))["sha"]
    except Exception:
        pass
    body = {"message": "tts samples: " + path, "content": base64.b64encode(data).decode(), "branch": "main"}
    if sha: body["sha"] = sha
    urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(body).encode(), headers=h, method="PUT")).read()

def publish():
    token = next(l.split("=", 1)[1].strip().strip("\"'") for l in open("/etc/vps-github-bridge/token") if l.startswith("GITHUB_TOKEN="))
    m = mk()
    raw = open(f"{IN}/raw.txt", encoding="utf-8").read()
    items = [(f"Silero · {sp}", f"silero_{sp}.mp3") for sp in SILERO_VOICES if os.path.exists(f"{OUT}/silero_{sp}.mp3")]
    for v in ["ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural"]:
        m._selected_voice = v
        p = f"{OUT}/edge_{v.split('-')[2].replace('Neural', '').lower()}.mp3"
        m.generate_block_tts(raw, p)
        if os.path.exists(p): items.append((f"edge-tts · {v}", os.path.basename(p)))
    html = ["<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>",
            "<title>Пробник озвучки</title><body style='font-family:sans-serif;max-width:640px;margin:16px auto;padding:0 12px'>",
            "<h2>Пробник озвучки</h2><p style='color:#555'>" + raw + "</p>"]
    for title, fn in items:
        html.append(f"<h4>{title}</h4><audio controls preload=none src='{fn}' style='width:100%'></audio>")
    for _, fn in items:
        put("docs/tts_samples/" + fn, open(f"{OUT}/{fn}", "rb").read(), token)
    put("docs/tts_samples/index.html", "\n".join(html).encode(), token)
    print("DONE", len(items), flush=True)

if __name__ == "__main__":
    {"prep": prep, "silero": silero, "publish": publish}[sys.argv[1]]()
