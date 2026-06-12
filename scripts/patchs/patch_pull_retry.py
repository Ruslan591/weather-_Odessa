FILE = 'scripts/update_local.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()
OLD = '''        subprocess.run(
            ["git", "-C", BASE_DIR, "pull", "--rebase", "origin", "main"],
            capture_output=True, text=True
        )
        push = subprocess.run(
            ["git", "-C", BASE_DIR, "push", "--force-with-lease"],
            capture_output=True, text=True
        )
        if push.returncode == 0:
            print("  git push \u2713")
        else:
            print(f"  git push \u2717: {push.stderr.strip()}")'''
NEW = '''        pull = subprocess.run(
            ["git", "-C", BASE_DIR, "pull", "--rebase", "origin", "main"],
            capture_output=True, text=True
        )
        if pull.returncode != 0:
            print(f"  git pull --rebase \u2717: {pull.stderr.strip()}")
            subprocess.run(
                ["git", "-C", BASE_DIR, "rebase", "--abort"],
                capture_output=True, text=True
            )
            pull = subprocess.run(
                ["git", "-C", BASE_DIR, "pull", "--rebase", "origin", "main"],
                capture_output=True, text=True
            )
            if pull.returncode != 0:
                print(f"  git pull --rebase (retry) \u2717: {pull.stderr.strip()}")
                return

        push = subprocess.run(
            ["git", "-C", BASE_DIR, "push", "--force-with-lease"],
            capture_output=True, text=True
        )
        if push.returncode == 0:
            print("  git push \u2713")
        else:
            print(f"  git push \u2717: {push.stderr.strip()}")'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
