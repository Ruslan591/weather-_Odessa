FILE = 'scripts/check_model_runs.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = '''        subprocess.run(["git", "-C", BASE_DIR, "add",
                        "data/model_runs_history.json",
                        f"data/synop_{year}.txt",
                        "data/model_bias.json",
                        "data/model_weights.json",
                        "data/forecast_analysis_claude.json", "data/forecast_analysis_claude.mp3",
                        "data/blocks"],
                      check=True, capture_output=True)'''

NEW = '''        subprocess.run(["git", "-C", BASE_DIR, "add",
                        "data/model_runs_history.json",
                        f"data/synop_{year}.txt",
                        "data/model_bias.json",
                        "data/model_weights.json",
                        "data/forecast_analysis_claude.json", "data/forecast_analysis_claude.mp3",
                        "data/forecast_video.mp4", "data/forecast_voice.mp3",
                        "data/blocks"],
                      check=True, capture_output=True)'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

OLD2 = '''                    # Коммитим видео и аудио после генерации
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

NEW2 = ''''''

assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")
