"""Figures for the README and results, as SVG in a light and a dark version. No plotting library.

    python -m prestige.eval.figures --out docs/figures

Per-task costs and cache splits come from the live traces in `runs/live`. Attack counts are the
published repeat-run totals in docs/RESULTS.md, kept here as data so a figure can't drift from the
table it shows.

Forms follow the statistical graphics literature: position on a common scale over area or angle
(Cleveland and McGill, 1984), every task shown as a point next to the summary (Weissgerber et al.,
2015), and one message per figure with the caption doing the explaining (Rougier et al., 2014).
"""

from __future__ import annotations

import argparse
import html
import random
from pathlib import Path

from prestige.eval.cache_report import split
from prestige.eval.live_report import cost_change, load_costs, wilson

# Validated reference palette. Each setup keeps its hue in every figure.
THEMES = {
    "light": {
        "surface": "#fcfcfb", "text": "#0b0b0b", "muted": "#52514e", "grid": "#e4e3df", "band": "#e8f0fb",
        "prestige": "#2a78d6", "none": "#eb6834", "guard": "#1baf7a",
        # causes in the cache figure: palette slots 4 to 6, so they never borrow a setup's hue
        "c1": "#eda100", "c2": "#e87ba4", "c3": "#008300", "on_c1": "#0b0b0b", "on_c2": "#0b0b0b", "on_c3": "#fcfcfb",
    },
    "dark": {
        "surface": "#1a1a19", "text": "#f0efec", "muted": "#c3c2b7", "grid": "#383835", "band": "#1f2f45",
        "prestige": "#3987e5", "none": "#d95926", "guard": "#199e70",
        "c1": "#c98500", "c2": "#d55181", "c3": "#008300", "on_c1": "#1a1a19", "on_c2": "#f0efec", "on_c3": "#f0efec",
    },
}
FONT = "font-family=\"-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif\""
W = 760
LEFT = 150  # room for row labels
RIGHT = 40

MODELS = (("Muse Spark 1.3", "main-benign"), ("Muse Spark Open", "open-benign"))
# Repeat runs on the pairs where an optimized attack lands. docs/RESULTS.md, Optimized attacks.
ATTACKS = (
    ("Muse Spark 1.3", "No gateway", 42, 70),
    ("Muse Spark 1.3", "Prestige", 0, 70),
    ("Muse Spark Open", "No gateway", 20, 40),
    ("Muse Spark Open", "Prestige", 0, 40),
)


def esc(text: str) -> str:
    return html.escape(text, quote=True)


class Svg:
    def __init__(self, height: int, theme: dict[str, str], title: str):
        self.t = theme
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" viewBox="0 0 {W} {height}" role="img" aria-label="{esc(title)}">',
            f"<title>{esc(title)}</title>",
            f'<rect width="{W}" height="{height}" fill="{theme["surface"]}"/>',
        ]

    def text(self, x: float, y: float, s: str, *, size: int = 13, color: str = "text", anchor: str = "start", weight: int = 400) -> None:
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" fill="{self.t[color]}" text-anchor="{anchor}">{esc(s)}</text>'
        )

    def line(self, x1: float, y1: float, x2: float, y2: float, color: str, width: float = 2, dash: str = "") -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{self.t[color]}" stroke-width="{width}" stroke-linecap="round"{d}/>')

    def dot(self, x: float, y: float, color: str, r: float = 5) -> None:
        # 2px surface ring keeps overlapping dots apart
        self.parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{self.t[color]}" stroke="{self.t["surface"]}" stroke-width="2"/>')

    def rect(self, x: float, y: float, w: float, h: float, color: str, radius: float = 4) -> None:
        self.parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{h:.1f}" rx="{radius}" fill="{self.t[color]}"/>')

    def done(self) -> str:
        return "\n".join(self.parts + ["</svg>"]) + "\n"


def axis(svg: Svg, x0: float, x1: float, top: float, bottom: float, ticks: list[tuple[float, str]]) -> None:
    """Recessive vertical gridlines with tick labels underneath."""
    for x, label in ticks:
        svg.line(x, top, x, bottom, "grid", 1)
        svg.text(x, bottom + 18, label, size=12, color="muted", anchor="middle")


def per_task(name: str, setup: str) -> dict[tuple[str, str], float]:
    costs = load_costs(Path("runs/live") / name / "trace.sqlite")
    out = {}
    for key, row in costs.items():
        s, st, task, injection = key.split(".")
        if st == setup and injection == "none":
            out[(s, task)] = row["cost"]
    return out


def fig_cost(theme: dict[str, str]) -> str:
    """Cost per task, guard only against Prestige, with each task's own change."""
    rows = []
    for label, name in MODELS:
        guard, prestige = per_task(name, "C"), per_task(name, "D")
        keys = sorted(set(guard) & set(prestige))
        total = cost_change(guard, prestige)
        changes = [100 * (prestige[k] / guard[k] - 1) for k in keys if guard[k]]
        rows.append((label, total, changes, sum(guard[k] for k in keys) / len(keys), sum(prestige[k] for k in keys) / len(keys)))

    h = 330
    svg = Svg(h, theme, "Prestige cuts cost per task by 40% on Muse Spark and 33% on Muse Spark Open")
    svg.text(24, 34, "Prestige cuts cost per task by a third or more", size=18, weight=600)
    svg.text(24, 56, "Change in each task's cost, Prestige against the guard alone. 57 tasks per model, live, Nov 2.", size=13, color="muted")
    lo, hi = -100, 200
    x = lambda v: LEFT + (min(max(v, lo), hi) - lo) / (hi - lo) * (W - LEFT - RIGHT)  # noqa: E731
    top, bottom = 80, 270
    axis(svg, LEFT, W - RIGHT, top, bottom, [(x(v), f"{v:+d}%" if v else "0") for v in range(-100, 201, 50)])
    svg.line(x(0), top, x(0), bottom, "muted", 1.5)
    rng = random.Random(7)  # fixed jitter so the figure is the same every build
    for i, (label, (change, ci_lo, ci_hi), changes, guard_cost, prestige_cost) in enumerate(rows):
        y = top + 50 + i * 95
        svg.text(LEFT - 14, y - 4, label, anchor="end", weight=600)
        svg.text(LEFT - 14, y + 14, f"${guard_cost:.4f} to ${prestige_cost:.4f}", anchor="end", size=12, color="muted")
        svg.rect(x(ci_lo), y - 30, x(ci_hi) - x(ci_lo), 60, "band", 4)  # 95% interval of the total change
        for c in changes:
            jitter = rng.uniform(-22, 22)
            svg.dot(x(c), y + jitter, "prestige", 4)
            if c > hi:  # drawn at the edge, labelled with its real value
                svg.text(x(hi) - 8, y + jitter + 4, f"{c:+.0f}%", anchor="end", size=11, color="muted")
        svg.line(x(change), y - 34, x(change), y + 34, "text", 2.5)
        svg.text(x(0) - 8, y - 40, f"{change:+.0f}% total (95% CI {ci_lo:+.0f}% to {ci_hi:+.0f}%)", anchor="end", size=12, weight=600)
    svg.text(24, h - 16, "Each dot is one task. Some cost more, since the model can take a longer path. The line is the change in total cost, the band its 95% interval.", size=11, color="muted")
    return svg.done()


def fig_attacks(theme: dict[str, str]) -> str:
    """Attack success with and without Prestige, with Wilson intervals."""
    h = 300
    svg = Svg(h, theme, "Optimized attacks that worked: 42 of 70 to 0 of 70 on Muse Spark, 20 of 40 to 0 of 40 on Muse Spark Open")
    svg.text(24, 34, "No optimized attack got through Prestige", size=18, weight=600)
    svg.text(24, 56, "Share of runs where the attack worked, on the pairs where it lands. 10 runs per pair, live.", size=13, color="muted")
    x = lambda p: LEFT + p * (W - LEFT - RIGHT - 120)  # noqa: E731
    top, bottom = 80, 240
    axis(svg, LEFT, W - RIGHT, top, bottom, [(x(p / 100), f"{p}%") for p in range(0, 101, 25)])
    for i, (model, setup, k, n) in enumerate(ATTACKS):
        y = top + 24 + i * 38 + (12 if i >= 2 else 0)
        if setup == "No gateway":
            svg.text(LEFT - 14, y + 16, model, anchor="end", weight=600)
        color = "none" if setup == "No gateway" else "prestige"
        lo, hi = wilson(k, n)
        svg.line(x(lo), y, x(hi), y, color, 2)
        svg.dot(x(k / n), y, color, 6)
        svg.text(x(hi) + 12, y + 4, f"{setup}: {k} of {n}", size=12)
    svg.text(24, h - 16, "Dot: observed share. Line: Wilson 95% interval. Attacks from AutoDojo's published set, never written here.", size=11, color="muted")
    return svg.done()


def fig_cache(theme: dict[str, str]) -> str:
    """Why input missed the cache, as one tall segmented bar per model."""
    causes = (("first call", "First call of a conversation", "c1"), ("new", "Content added since the last call", "c2"), ("provider miss", "Same prefix, provider didn't cache it", "c3"))
    rows = []
    for label, name in MODELS:
        row = split(Path("runs/live") / name / "trace.sqlite")["D"]
        uncached = row["input"] - row["cached"]
        rows.append((label, 100 * row["cached"] / row["input"], [100 * row[c] / uncached for c, _, _ in causes], 100 * row["changed"] / uncached))
    h = 300
    svg = Svg(h, theme, "Why the uncached input missed the cache, under Prestige")
    svg.text(24, 34, "The prompt never broke. What's left is new content and the provider", size=18, weight=600)
    svg.text(24, 56, "Uncached input tokens under Prestige, split by cause. From the live traces.", size=13, color="muted")
    x0, x1 = LEFT, W - RIGHT
    for i, (label, cached, shares, changed) in enumerate(rows):
        y = 90 + i * 70
        svg.text(LEFT - 14, y + 13, label, anchor="end", weight=600)
        svg.text(LEFT - 14, y + 30, f"{cached:.0f}% of input from cache", anchor="end", size=12, color="muted")
        cursor = x0
        for share, (_, _, color) in zip(shares, causes):
            w = share / 100 * (x1 - x0)
            svg.rect(cursor, y, w - 2, 28, color, 4)  # 2px surface gap between blocks
            if w > 44:
                svg.text(cursor + 8, y + 19, f"{share:.0f}%", size=12, weight=600, color="on_" + color)
            cursor += w
    ly = 250
    lx = 24
    for _, name, color in causes:
        svg.rect(lx, ly - 10, 12, 12, color, 3)
        svg.text(lx + 18, ly, name, size=12)
        lx += 18 + len(name) * 6.6 + 24
    svg.text(24, h - 16, "Changed prefix: 0% on both models. Baseten caches in 64-token blocks, so most of its misses are rounding.", size=11, color="muted")
    return svg.done()


FIGURES = {"cost": fig_cost, "attacks": fig_attacks, "cache": fig_cache}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prestige.eval.figures", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="docs/figures")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, build in FIGURES.items():
        for mode, theme in THEMES.items():
            path = out / f"{name}-{mode}.svg"
            path.write_text(build(theme), encoding="utf-8")
            print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
