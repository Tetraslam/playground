#!/usr/bin/env python3
"""Parse a lain-exported node markdown file into toy-scaffold material.

The playground treats `lain` as a black box: it runs `lain export <db> --out
<dir>` (a public command) and this script reads the resulting `<node>.md` files
— stable markdown with YAML frontmatter. We never touch lain's internals/schema.

Modes:
    _lain_toy.py list   <export-dir>            # list node ids + titles
    _lain_toy.py readme <export-dir> <node-id>  # emit a toy README.md
    _lain_toy.py slug   <export-dir> <node-id>  # emit a dir-safe slug for the title
"""
import re
import sys
from pathlib import Path


def parse_node(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    meta, body = {}, text
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        for line in fm.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    body = body.strip()
    # title = first markdown H1
    m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    title = m.group(1).strip() if m else meta.get("id", path.stem)
    # "direction" one-liner often appears as the node's framing; grab first
    # non-empty paragraph after the title (skipping wikilink lines).
    direction = ""
    after = body[m.end():] if m else body
    for para in after.split("\n\n"):
        p = para.strip()
        if p and not p.startswith("[[") and not p.startswith("#"):
            direction = re.sub(r"\s+", " ", p)
            break
    return {"meta": meta, "title": title, "direction": direction, "body": body}


def slugify(s: str) -> str:
    s = s.lower()
    # take text before a colon (lain titles are "Name: tagline")
    s = s.split(":")[0]
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:40] or "toy"


def nodes(export_dir: Path):
    for p in sorted(export_dir.glob("*.md")):
        if p.stem in ("_index", "root"):
            continue
        yield p


def main():
    mode = sys.argv[1]
    export_dir = Path(sys.argv[2])

    if mode == "list":
        for p in nodes(export_dir):
            n = parse_node(p)
            print(f"{n['meta'].get('id', p.stem)}\t{n['title']}")
        return

    node_id = sys.argv[3]
    path = export_dir / f"{node_id}.md"
    if not path.exists():
        sys.stderr.write(f"_lain_toy: node {node_id} not found in {export_dir}\n")
        sys.exit(1)
    n = parse_node(path)

    if mode == "slug":
        print(slugify(n["title"]))
    elif mode == "readme":
        title = n["title"]
        # Build a toy README that carries the idea forward.
        print(f"# {slugify(title)}\n")
        if n["direction"]:
            print(f"> {n['direction']}\n")
        print(f"_Scaffolded from a `lain` exploration node (`{node_id}`). The "
              f"design below is the idea — go build it._\n")
        # include the full node body (minus the duplicate H1) as the design doc
        body = re.sub(r"^#\s+.+\n", "", n["body"], count=1).strip()
        # drop wikilink parent lines
        body = "\n".join(l for l in body.splitlines() if not l.strip().startswith("[["))
        print(body.strip())
        print("\n## Status\n")
        print("Scaffolded stub — not built yet. Pick a language and build the "
              "*system* behind the idea: the real algorithm, the thing that "
              "runs over time, the part that's genuinely hard. A view is fine, "
              "but it's the window onto the system, not the toy itself. Aim for "
              "depth over a screenshot.")


if __name__ == "__main__":
    main()
