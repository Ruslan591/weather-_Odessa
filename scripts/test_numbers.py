# -*- coding: utf-8 -*-
"""Тест нумерации: python test_numbers.py <каталог с tg_shadow.py> <копия shadow.json>. Печатает строку nums ..."""
import os, sys, shutil
d = "/tmp/sh9test"; shutil.rmtree(d, ignore_errors=True); os.makedirs(d); shutil.copy(sys.argv[2], d + "/shadow.json")
os.environ["POS_DIR"] = d; sys.path.insert(0, sys.argv[1])
import tg_shadow as s
s._load(); by = {i["id"]: i for i in s.S["items"]}
print("nums", s.tag(by[61]), s.tag(by[62]), s.tag(by[65]), s.tag(by[66]), s.tag(by[67]), s.tag(by[68]), s.tags([62, 61]), s.S["nseq"])
