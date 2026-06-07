FILE = 'scripts/check_model_runs.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = '''            ai_result = subprocess.run(ai_cmd, cwd=BASE_DIR, capture_output=False)
            subprocess.run(
                [PYTHON, os.path.join(SCRIPTS_DIR, "make_blocks.py")],
                cwd=BASE_DIR, capture_output=False
            )
            if ai_result.returncode == 0:
                import json, os as _os
                _ai_file = _os.path.join(BASE_DIR, "data", "forecast_analysis_claude.json")
                _ai_changed = False
                try:
                    with open(_ai_file, encoding="utf-8") as _f:
                        _ai_changed = json.load(_f).get("changed", False)
                except Exception:
                    pass
                if _ai_changed:
                    subprocess.run(
                        [PYTHON, _os.path.join(SCRIPTS_DIR, "make_video.py")],
                        cwd=BASE_DIR, capture_output=False
                    )'''

NEW = '''            ai_result = subprocess.run(ai_cmd, cwd=BASE_DIR, capture_output=False)
            if ai_result.returncode == 0:
                import json, os as _os
                _ai_file = _os.path.join(BASE_DIR, "data", "forecast_analysis_claude.json")
                _ai_changed = False
                try:
                    with open(_ai_file, encoding="utf-8") as _f:
                        _ai_changed = json.load(_f).get("changed", False)
                except Exception:
                    pass
                if _ai_changed:
                    subprocess.run(
                        [PYTHON, _os.path.join(SCRIPTS_DIR, "make_blocks.py")],
                        cwd=BASE_DIR, capture_output=False
                    )
                    subprocess.run(
                        [PYTHON, _os.path.join(SCRIPTS_DIR, "make_video.py")],
                        cwd=BASE_DIR, capture_output=False
                    )'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")
