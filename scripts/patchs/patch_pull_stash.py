FILE = 'scripts/update_local.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()
OLD = '''        pull = subprocess.run(
            ["git", "-C", BASE_DIR, "pull", "--rebase", "origin", "main"],
            capture_output=True, text=True
        )
        if pull.returncode != 0:
            print(f"  git pull --rebase ✗: {pull.stderr.strip()}")
            subprocess.run(
                ["git", "-C", BASE_DIR, "rebase", "--abort"],
                capture_output=True, text=True
            )
            pull = subprocess.run(
                ["git", "-C", BASE_DIR, "pull", "--rebase", "origin", "main"],
                capture_output=True, text=True
            )
            if pull.returncode != 0:
                print(f"  git pull --rebase (retry) ✗: {pull.stderr.strip()}")
                return'''
NEW = '''        # Прячем возможные unstaged-изменения (напр. data/forecast_days.json
        # от generate_ai_analysis.py), чтобы pull --rebase не падал на "unstaged changes"
        stash = subprocess.run(
            ["git", "-C", BASE_DIR, "stash", "--include-untracked"],
            capture_output=True, text=True
        )
        stashed = "No local changes to save" not in (stash.stdout + stash.stderr)

        pull = subprocess.run(
            ["git", "-C", BASE_DIR, "pull", "--rebase", "origin", "main"],
            capture_output=True, text=True
        )
        if pull.returncode != 0:
            print(f"  git pull --rebase ✗: {pull.stderr.strip()}")
            subprocess.run(
                ["git", "-C", BASE_DIR, "rebase", "--abort"],
                capture_output=True, text=True
            )
            pull = subprocess.run(
                ["git", "-C", BASE_DIR, "pull", "--rebase", "origin", "main"],
                capture_output=True, text=True
            )
            if pull.returncode != 0:
                print(f"  git pull --rebase (retry) ✗: {pull.stderr.strip()}")
                if stashed:
                    subprocess.run(["git", "-C", BASE_DIR, "stash", "pop"], capture_output=True, text=True)
                return

        if stashed:
            pop = subprocess.run(["git", "-C", BASE_DIR, "stash", "pop"], capture_output=True, text=True)
            if pop.returncode != 0:
                print(f"  git stash pop ✗: {pop.stderr.strip()}")'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
