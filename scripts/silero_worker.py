#!/usr/bin/env python3
"""Воркер запасной озвучки Silero (v4_ru). Запускается ТОЛЬКО из make_blocks_gemini_cloud._silero_fallback
в песочнице (nobody, без сети: unshare -n + setpriv), потому что модель .pt — pickle из неофициального зеркала.
Не импортирует ничего из репо. Вход: <wd>/in.json {voice, tempo, sentences[]}; выход: <wd>/out.mp3 (24 кГц, mono)
и <wd>/out.json {sentences:[{start,end}], duration} — тайминги уже с учётом tempo.
Usage: silero_worker.py <wd> <model.pt>"""
import sys, os, json, wave, subprocess
import numpy as np
import torch

SR = 48000
GAP = 0.3
MAXLEN = 700

def split_long(s):
    if len(s) <= MAXLEN:
        return [s]
    parts, cur = [], ""
    for piece in s.split(", "):
        if len(cur) + len(piece) + 2 > MAXLEN and cur:
            parts.append(cur + ","); cur = piece
        else:
            cur = (cur + ", " + piece) if cur else piece
    if cur: parts.append(cur)
    return parts

def main():
    wd, model_path = sys.argv[1], sys.argv[2]
    cfg = json.load(open(os.path.join(wd, "in.json"), encoding="utf-8"))
    voice, tempo, sents = cfg["voice"], float(cfg.get("tempo", 1.0)), cfg["sentences"]
    torch.set_num_threads(2)
    model = torch.package.PackageImporter(model_path).load_pickle("tts_models", "model")
    model.to(torch.device("cpu"))
    chunks, spans, t = [], [], 0.0
    for s in sents:
        start = t
        if any(ch.isalnum() for ch in s):
            for part in split_long(s):
                a = model.apply_tts(text=part, speaker=voice, sample_rate=SR, put_accent=True, put_yo=True).numpy()
                chunks.append(a); t += len(a) / SR
        else:
            chunks.append(np.zeros(int(SR * 0.2), dtype="float32")); t += 0.2
        spans.append((start, t))
        chunks.append(np.zeros(int(SR * GAP), dtype="float32")); t += GAP
    pcm = (np.clip(np.concatenate(chunks), -1, 1) * 32767).astype("int16")
    wav = os.path.join(wd, "out.wav")
    with wave.open(wav, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SR); wf.writeframes(pcm.tobytes())
    mp3 = os.path.join(wd, "out.mp3")
    af = f"atempo={tempo}" if abs(tempo - 1.0) > 1e-3 else "anull"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-af", af, "-ar", "24000", "-ac", "1",
                    "-c:a", "libmp3lame", "-q:a", "4", mp3], check=True)
    os.remove(wav)
    out = {"sentences": [{"start": round(a / tempo, 3), "end": round(b / tempo, 3)} for a, b in spans],
           "duration": round(t / tempo, 3)}
    json.dump(out, open(os.path.join(wd, "out.json"), "w"))

if __name__ == "__main__":
    main()
