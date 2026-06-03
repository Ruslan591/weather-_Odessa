FILE = 'scripts/generate_ai_analysis.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = '''def load_api_key():
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                if line.startswith("ANTHROPIC_API_KEY="):
                    return line.strip().split("=", 1)[1]
    return os.environ.get("ANTHROPIC_API_KEY")'''
NEW = '''def load_api_key():
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                if line.startswith("ANTHROPIC_API_KEY="):
                    return line.strip().split("=", 1)[1]
    return os.environ.get("ANTHROPIC_API_KEY")

def ai_enabled():
    """Проверяет флаг AI_ANALYSIS_ENABLED в .env (default: true)."""
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                if line.startswith("AI_ANALYSIS_ENABLED="):
                    val = line.strip().split("=", 1)[1].lower()
                    return val not in ("0", "false", "no", "off")
    return True'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

OLD2 = '''    api_key = load_api_key()
    if not api_key:
        print("  [AI] ANTHROPIC_API_KEY не найден — пропускаю генерацию анализа")
        return'''
NEW2 = '''    if not ai_enabled():
        print("  [AI] Анализ отключён (AI_ANALYSIS_ENABLED=false в .env)")
        return

    api_key = load_api_key()
    if not api_key:
        print("  [AI] ANTHROPIC_API_KEY не найден — пропускаю генерацию анализа")
        return'''
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")