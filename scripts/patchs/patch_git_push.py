FILE = '/storage/emulated/0/Documents/weather/scripts/check_model_runs.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = '''                        "data/forecast_analysis_claude.json", "data/forecast_analysis_claude.mp3"],'''

NEW = '''                        "data/forecast_analysis_claude.json", "data/forecast_analysis_claude.mp3",
                        "data/blocks"],'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("git_push_history patched OK")
