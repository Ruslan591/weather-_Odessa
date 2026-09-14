#!/usr/bin/env python3
"""Добавляет ?v=<sha> ко всем локальным <script src=...>/<link href=...> (.js/.css)
во всех .html перед публикацией на GitHub Pages. Работает только в CI-раннере,
в репозиторий эти правки не коммитятся — исходники в git остаются без версии."""
import re, sys, glob

sha = sys.argv[1] if len(sys.argv) > 1 else "0"
SRC_RE = re.compile(r'(src|href)="([^"]+?)(\?[^"]*)?"')

def is_local(url):
    return not url.startswith(("http://", "https://", "//"))

def bust(path):
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    def repl(m):
        attr, url = m.group(1), m.group(2)
        if not is_local(url) or not (url.endswith(".js") or url.endswith(".css")):
            return m.group(0)
        return f'{attr}="{url}?v={sha}"'

    new_html = SRC_RE.sub(repl, html)
    if new_html != html:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_html)
        print(f"cache-busted: {path}")

for path in glob.glob("**/*.html", recursive=True):
    bust(path)
