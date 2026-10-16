#!/usr/bin/env python3
"""A titkosított feed olvasása (Claude ezt használja a chatben, de helyben is működik).
  FEED_KEY=... python3 feed_read.py               # index
  FEED_KEY=... python3 feed_read.py <elemzes-név>  # egy aktivitás elemzése"""
import json, os, sys, urllib.request
from feedcrypt import decrypt

BASE = "https://raw.githubusercontent.com/zzbaji/garmin-sync/feed/data"


def get(path):
    with urllib.request.urlopen(f"{BASE}/{path}", timeout=30) as r:
        return json.loads(decrypt(os.environ["FEED_KEY"], r.read()))


if __name__ == "__main__":
    obj = get(f"a/{sys.argv[1]}.enc") if len(sys.argv) > 1 else get("index.enc")
    print(json.dumps(obj, ensure_ascii=False, indent=2))
