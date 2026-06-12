FILE = 'scripts/update_local.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()
OLD = '''def git_commit_push(no_push=False):
    try:
        if _GIT_CHANGED:'''
NEW = '''def git_commit_push(no_push=False):
    try:
        subprocess.run(
            ["git", "-C", BASE_DIR, "fetch", "origin", "main"],
            capture_output=True, text=True
        )
        if _GIT_CHANGED:'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
