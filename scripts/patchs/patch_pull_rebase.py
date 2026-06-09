FILE = 'scripts/update_local.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''        push = subprocess.run(
            ["git", "-C", BASE_DIR, "push", "--force-with-lease"],
            capture_output=True, text=True
        )'''
NEW = '''        subprocess.run(
            ["git", "-C", BASE_DIR, "pull", "--rebase", "origin", "main"],
            capture_output=True, text=True
        )
        push = subprocess.run(
            ["git", "-C", BASE_DIR, "push", "--force-with-lease"],
            capture_output=True, text=True
        )'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
