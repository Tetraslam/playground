#!/usr/bin/env python3
"""Parser for links.sh. Reads the gathered markdown feed (upstream + local)
and either lists a tag cloud or filters entries by AND-matched tags.

Usage:
    _links_parse.py --tags   <feed-file>
    _links_parse.py --filter <feed-file> [tag ...]
"""
import collections
import re
import sys


def entries(path):
    title = url = None
    tags = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("### "):
                if title and url:
                    yield title, url, tags
                title, url, tags = line[4:].strip(), None, []
            elif "**Tags**:" in line:
                m = re.search(r"\*\*Tags\*\*:\s*(.+)", line)
                tags = [x.strip().lower() for x in m.group(1).split(",")] if m else []
            elif "**URL**:" in line:
                m = re.search(r"\*\*URL\*\*:\s*(\S+)", line)
                url = m.group(1) if m else None
    if title and url:
        yield title, url, tags


def main():
    mode = sys.argv[1]
    feed = sys.argv[2]
    if mode == "--tags":
        counts = collections.Counter()
        for _, _, tags in entries(feed):
            counts.update(tags)
        for tag, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"{n:4}  {tag}")
    elif mode == "--filter":
        want = [t.lower() for t in sys.argv[3:]]
        for title, url, tags in entries(feed):
            if want and not all(w in tags for w in want):
                continue
            tg = ",".join(tags)
            print(f"- {title}\n    {url}" + (f"\n    [{tg}]" if tg else ""))


if __name__ == "__main__":
    main()
