FILE = 'scripts/check_model_runs.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = '''                if _ai_changed:
                    subprocess.run(
                        [PYTHON, _os.path.join(SCRIPTS_DIR, "make_blocks.py")],
                        cwd=BASE_DIR, capture_output=False
                    )
                    subprocess.run(
                        [PYTHON, _os.path.join(SCRIPTS_DIR, "make_video.py")],
                        cwd=BASE_DIR, capture_output=False
                    )
                    # Коммитим видео и аудио после генерации
                    import subprocess as _sp
                    _video_files = [
                        "data/forecast_video.mp4",
                        "data/forecast_voice.mp3",
                        "data/blocks/blocks_meta.json",
                    ]
                    _sp.run(["git", "-C", BASE_DIR, "add"] + _video_files,
                            capture_output=True)
                    _sp.run(["git", "-C", BASE_DIR, "commit", "-m", "auto: обновление видео и блоков"],
                            capture_output=True)
                    _sp.run(["git", "-C", BASE_DIR, "push", "--force-with-lease"],
                            capture_output=True)
                    print("  git: видео запушено")'''

NEW = '''                if _ai_changed:
                    _blocks_meta = _os.path.join(BASE_DIR, "data", "blocks", "blocks_meta.json")
                    _old_hash = ""
                    try:
                        with open(_blocks_meta, encoding="utf-8") as _f:
                            _old_hash = json.load(_f).get("data_hash", "")
                    except Exception:
                        pass
                    subprocess.run(
                        [PYTHON, _os.path.join(SCRIPTS_DIR, "make_blocks.py")],
                        cwd=BASE_DIR, capture_output=False
                    )
                    _new_hash = ""
                    try:
                        with open(_blocks_meta, encoding="utf-8") as _f:
                            _new_hash = json.load(_f).get("data_hash", "")
                    except Exception:
                        pass
                    if _new_hash and _new_hash != _old_hash:
                        subprocess.run(
                            [PYTHON, _os.path.join(SCRIPTS_DIR, "make_video.py")],
                            cwd=BASE_DIR, capture_output=False
                        )
                    else:
                        print("  [VIDEO] Блоки не изменились — пропускаю генерацию видео")'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

# Добавляем forecast_video.mp4 в git_push_history
OLD2 = '''        subprocess.run(["git", "-C", BASE_DIR, "add",
                        "data/model_runs_history.json",
                        f"data/synop_{year}.txt",
                        "data/model_bias.json",
                        "data/model_weights.json",
                        "data/forecast_analysis_claude.json", "data/forecast_analysis_claude.mp3",
                        "data/blocks"],
                      check=True, capture_output=True)'''

NEW2 = '''        subprocess.run(["git", "-C", BASE_DIR, "add",
                        "data/model_runs_history.json",
                        f"data/synop_{year}.txt",
                        "data/model_bias.json",
                        "data/model_weights.json",
                        "data/forecast_analysis_claude.json", "data/forecast_analysis_claude.mp3",
                        "data/forecast_video.mp4", "data/forecast_voice.mp3",
                        "data/blocks"],
                      check=True, capture_output=True)'''

assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")
