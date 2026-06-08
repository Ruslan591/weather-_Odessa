FILE = 'scripts/check_model_runs.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''                    if _blocks_result.returncode == 0:
                        subprocess.run(
                            [PYTHON, _os.path.join(SCRIPTS_DIR, "make_video.py")],
                            cwd=BASE_DIR, capture_output=False
                        )
                        if _os.path.exists(_pending_file):
                            _os.remove(_pending_file)'''
NEW = '''                    if _blocks_result.returncode == 0:
                        # make_video \u043e\u0442\u043a\u043b\u044e\u0447\u0451\u043d
                        if _os.path.exists(_pending_file):
                            _os.remove(_pending_file)'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

OLD2 = '''            if _b.returncode == 0:
                subprocess.run(
                    [PYTHON, os.path.join(SCRIPTS_DIR, "make_video.py")],
                    cwd=BASE_DIR, capture_output=False
                )
                os.remove(_pending_file)'''
NEW2 = '''            if _b.returncode == 0:
                # make_video \u043e\u0442\u043a\u043b\u044e\u0447\u0451\u043d
                os.remove(_pending_file)'''
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
