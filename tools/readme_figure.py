#!/usr/bin/env python3
"""Draw the figure at the top of README.md from runs/field-v2/scores.json.

    python3 tools/readme_figure.py

Writes docs/images/pairs-light.svg and docs/images/pairs-dark.svg, and prints the sentence the figure's alt text uses.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "runs" / "field-v2" / "scores.json"
OUT = ROOT / "docs" / "images"
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
THEMES = {
    "light": {"text": "#0b0b0b", "muted": "#52514e", "bar": "#2a78d6"},
    "dark": {"text": "#f0efec", "muted": "#c3c2b7", "bar": "#3987e5"},
}
# (key in pair_outcomes, label): tools/score.py defines the four outcomes.
ROWS = [
    ("trigger_happy", "Said Yes to both clips"),
    ("discriminated", "Correct: Yes with the event, No without it"),
    ("blind", "Said No to both clips"),
    ("inverted", "No with the event, Yes without it"),
]
WIDTH, LABELS, ROW, BAR, VALUE_ROOM = 860, 330, 34, 20, 50


def read():
    """Return {outcome: count}, summed over every model and event."""
    if not SOURCE.is_file():
        sys.exit(f"readme_figure: {SOURCE} not found")
    total = {}
    for score in json.loads(SOURCE.read_text(encoding="utf-8")):
        for key, value in score["pair_outcomes"].items():
            total[key] = total.get(key, 0) + value
    if not total:
        sys.exit(f"readme_figure: no pair outcomes in {SOURCE}")
    return total


def text(x, y, body, size, fill, weight="400"):
    return f'<text x="{x:g}" y="{y:g}" font-size="{size}" font-weight="{weight}" fill="{fill}">{body}</text>'


def draw(total, title, note, theme, desc):
    c = THEMES[theme]
    unit = (WIDTH - LABELS - VALUE_ROOM) / max(total[k] for k, _ in ROWS)
    parts = [text(0, 28, title, 20, c["text"], "600"), text(0, 52, note, 14, c["muted"])]
    y = 78
    for key, label in ROWS:
        parts.append(text(0, y + 15, label, 15, c["text"]))
        w = total[key] * unit
        parts.append(f'<rect x="{LABELS}" y="{y}" width="{w:g}" height="{BAR}" rx="4" fill="{c["bar"]}"/>')
        parts.append(text(LABELS + w + 8, y + 15, str(total[key]), 15, c["text"], "600"))
        y += ROW
    height = y
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height:g}" width="{WIDTH}" height="{height:g}" '
        f'role="img" aria-labelledby="t d" font-family="{FONT}">\n'
        f'<title id="t">{title}</title>\n<desc id="d">{desc}</desc>\n' + "\n".join(parts) + "\n</svg>\n"
    )


def main():
    total = read()
    title = f"Asked if an event happened: {sum(total.values())} results on matched pairs of clips"
    note = "Each result is one model on one pair of clips, with and without the event, each shown as 1, 2, 6 or 12 frames in one image."
    desc = f"{title}. {note} " + " ".join(f"{label}: {total[key]}." for key, label in ROWS)
    OUT.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        (OUT / f"pairs-{theme}.svg").write_text(draw(total, title, note, theme, desc), encoding="utf-8")
    print(desc)


if __name__ == "__main__":
    main()
