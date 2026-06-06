FILE = '/storage/emulated/0/Documents/weather/scripts/check_model_runs.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = '''        if ok:
            subprocess.run(
                [PYTHON, os.path.join(SCRIPTS_DIR, "generate_ai_analysis.py")],
                cwd=BASE_DIR, capture_output=False
            )
        git_push_history()'''

NEW = '''        if ok:
            subprocess.run(
                [PYTHON, os.path.join(SCRIPTS_DIR, "generate_ai_analysis.py")],
                cwd=BASE_DIR, capture_output=False
            )
            subprocess.run(
                [PYTHON, os.path.join(SCRIPTS_DIR, "make_blocks.py")],
                cwd=BASE_DIR, capture_output=False
            )
        git_push_history()'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("check_model_runs.py patched OK")
