#!/usr/bin/env python3
"""Character count as X counts it, for the free tier's 280.

Two rules that make a hand count wrong: a URL is 23 characters whatever its real
length, and CJK weighs double — so a Japanese post has an effective budget of 140
characters, not 280. A draft that looks fine in an editor can be forty over.

usage: x_len.py "label" "the post text" ["label2" "text2" ...]
"""
import re, sys
URL = re.compile(r'https?://\S+|(?<![\w.])(?:[\w-]+\.)+(?:com|io|org|net|ai|co)/\S*')
def x_len(s):
    # X counts any URL as 23 characters, and CJK as 2 weighted units against a
    # 280 budget — i.e. a Japanese post is effectively 140 characters.
    t = URL.sub("x"*23, s.strip())
    w = 0
    for ch in t:
        w += 2 if ('　' <= ch <= '鿿' or '＀' <= ch <= '￯') else 1
    return len(t), w
for name, body in [(a, b) for a, b in zip(sys.argv[1::2], sys.argv[2::2])]:
    n, w = x_len(body)
    print(f"  {name:<12} {n:>4} chars   weighted {w:>4}/280   {'OK' if w<=280 else 'OVER by '+str(w-280)}")
