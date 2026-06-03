FILE = 'scripts/check_model_runs.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = '''    if new_models:
        save_history(history)
        run_pipeline(new_models)
        git_push_history()'''
NEW = '''    if new_models:
        save_history(history)
        ok = run_pipeline(new_models)
        if ok:
            subprocess.run(
                [PYTHON, os.path.join(SCRIPTS_DIR, "generate_ai_analysis.py")],
                cwd=BASE_DIR, capture_output=False
            )
        git_push_history()'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

# Добавить data/forecast_analysis.json в git_push_history
OLD2 = '''        subprocess.run(["git", "-C", BASE_DIR, "add",
                        "data/model_runs_history.json",
                        f"data/synop_{year}.txt",
                        "data/model_bias.json",
                        "data/model_weights.json"],'''
NEW2 = '''        subprocess.run(["git", "-C", BASE_DIR, "add",
                        "data/model_runs_history.json",
                        f"data/synop_{year}.txt",
                        "data/model_bias.json",
                        "data/model_weights.json",
                        "data/forecast_analysis.json"],'''
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")