FILE = 'scripts/make_video.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''def extract_temp_range(text):
    nums = [int(m) for m in __import__('re').findall(r\'(-?\d{1,2})\u00b0C\', text)]
    if not nums: return None, None
    return min(nums), max(nums)'''
NEW = '''def extract_temp_range(text):
    import re
    nums = [int(m) for m in re.findall(r\'(-?\d{1,2})\u00b0C\', text)]
    nums = [n for n in nums if -30 <= n <= 45]
    if not nums: return None, None
    return min(nums), max(nums)'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
