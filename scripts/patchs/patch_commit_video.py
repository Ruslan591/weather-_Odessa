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
                    )'''

NEW = '''                if _ai_changed:
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

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")
