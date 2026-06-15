#!/usr/bin/env python3
"""Insert a feedback entry under the right section header in FEEDBACK.md.

If the section currently holds the "_(none yet)_" placeholder, replace it;
otherwise prepend the entry as the newest item under the header.

Usage: _feedback_insert.py <file> <header> <entry>
"""
import io
import sys


def main():
    path, header, entry = sys.argv[1], sys.argv[2], sys.argv[3]
    with io.open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")

    out, inserted, i = [], False, 0
    while i < len(lines):
        out.append(lines[i])
        if not inserted and lines[i].strip() == header.strip():
            k = i + 1
            while k < len(lines) and lines[k].strip() == "":
                k += 1
            if k < len(lines) and lines[k].strip() == "_(none yet)_":
                out.append("")
                out.append(entry)
                i = k + 1
                inserted = True
                continue
            else:
                out.append("")
                out.append(entry)
                inserted = True
        i += 1

    if not inserted:
        sys.stderr.write("feedback: section header not found, nothing appended\n")
        sys.exit(1)

    with io.open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


if __name__ == "__main__":
    main()
