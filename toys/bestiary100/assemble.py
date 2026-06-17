#!/usr/bin/env python3
"""Assemble the Bestiary of the Drift from individual creature files.

Reads all creatures/N.md files, parses the YAML frontmatter, and generates
a field guide index (INDEX.md) grouped by biome with links to each creature.

Usage:
    uv run --no-project toys/bestiary100/assemble.py
"""

from __future__ import annotations

import re
from pathlib import Path

CREATURES_DIR = Path(__file__).parent / "creatures"
OUTPUT = Path(__file__).parent / "INDEX.md"

BIOME_ORDER = [
    "the Vent",
    "Canopy",
    "Underglow",
    "Glass Wastes",
    "Aether",
    "Mire",
    "Bone Fields",
    "Rime",
]

BIOME_DESC = {
    "the Vent": "thermal deeps, geothermal fissures, dark",
    "Canopy": "the upper surface of world-trees, sunlit, vast",
    "Underglow": "bioluminescent fungal forests below the canopy",
    "Glass Wastes": "crystalline deserts, refractive, scorching",
    "Aether": "the open sky between landmasses, thin air",
    "Mire": "swampy lower drift, organic decay, dense",
    "Bone Fields": "fossil-rich badlands, calcified remains",
    "Rime": "frozen upper atmosphere, crystalline ice",
}


def parse_frontmatter(text: str) -> dict:
    """Parse simple YAML frontmatter from a markdown file."""
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            # parse list values [a, b, c]
            if val.startswith("[") and val.endswith("]"):
                val = [v.strip().strip("\"'") for v in val[1:-1].split(",") if v.strip()]
            fm[key] = val
    return fm


def get_body(text: str) -> str:
    """Get the markdown body (after frontmatter)."""
    m = re.match(r"^---\n.*?\n---\n(.*)", text, re.DOTALL)
    return m.group(1).strip() if m else text


def main() -> None:
    creatures = []
    for md_path in sorted(CREATURES_DIR.glob("*.md"), key=lambda p: int(p.stem)):
        text = md_path.read_text()
        fm = parse_frontmatter(text)
        creatures.append({
            "id": fm.get("id", md_path.stem),
            "name": fm.get("name", "???"),
            "biome": fm.get("biome", "???"),
            "diet": fm.get("diet", "???"),
            "size": fm.get("size", "???"),
            "temperament": fm.get("temperament", "???"),
            "tags": fm.get("tags", []),
            "file": md_path.name,
            "svg": md_path.stem + ".svg",
        })

    # group by biome
    by_biome: dict[str, list] = {b: [] for b in BIOME_ORDER}
    for c in creatures:
        b = c["biome"]
        if b not in by_biome:
            by_biome[b] = []
        by_biome[b].append(c)

    # build index
    lines = [
        "# Bestiary of the Drift",
        "",
        f"100 creatures, 8 biomes, 100 subagents, one alien world.",
        "",
        f"| biome | creatures |",
        f"|-------|-----------|",
    ]
    for b in BIOME_ORDER:
        if b in by_biome and by_biome[b]:
            lines.append(f"| {b} | {len(by_biome[b])} |")
    lines.append("")

    for b in BIOME_ORDER:
        entries = by_biome.get(b, [])
        if not entries:
            continue
        lines.append(f"## {b}")
        lines.append(f"*{BIOME_DESC.get(b, '')}*")
        lines.append("")
        lines.append("| # | name | diet | size | temperament |")
        lines.append("|---|------|------|------|-------------|")
        for c in sorted(entries, key=lambda x: int(x["id"])):
            lines.append(
                f"| {c['id']} | [{c['name']}](creatures/{c['file']}) "
                f"| {c['diet']} | {c['size']} | {c['temperament']} |"
            )
        lines.append("")

    OUTPUT.write_text("\n".join(lines))
    print(f"wrote {OUTPUT} ({len(creatures)} creatures, {len(by_biome)} biomes)")


if __name__ == "__main__":
    main()
