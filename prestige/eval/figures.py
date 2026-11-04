"""Figures for the README and results, as SVG. Each comes in light and dark, static and animated.

    python -m prestige.eval.figures --out docs/figures

Per-task costs and cache splits come from the live traces in `runs/live`. Attack counts are the
published repeat-run totals in docs/RESULTS.md, kept here as data so a figure can't drift from the
table it shows. The figures carry axis labels and legends only. Captions live in the documents.

Forms follow the statistical graphics literature: position on a common scale over area or angle
(Cleveland and McGill, 1984), every task shown as a point next to the summary (Weissgerber et al.,
2015), and one message per figure with the caption doing the explaining (Rougier et al., 2014).
The animated versions play once and stay still for readers who ask for reduced motion.
"""

from __future__ import annotations

import argparse
import html
import random
import sqlite3
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
        # parts of a task's cost: slots 7 and 8, with cached input in a recessive gray
        "out": "#6250d6", "unc": "#e34948", "cac": "#b8b6ae", "on_out": "#fcfcfb", "on_unc": "#fcfcfb", "on_cac": "#0b0b0b",
    },
    "dark": {
        "surface": "#1a1a19", "text": "#f0efec", "muted": "#c3c2b7", "grid": "#383835", "band": "#1f2f45",
        "prestige": "#3987e5", "none": "#d95926", "guard": "#199e70",
        "c1": "#c98500", "c2": "#d55181", "c3": "#008300", "on_c1": "#1a1a19", "on_c2": "#f0efec", "on_c3": "#f0efec",
        "out": "#9085e9", "unc": "#e66767", "cac": "#6b6a64", "on_out": "#1a1a19", "on_unc": "#1a1a19", "on_cac": "#f0efec",
    },
}
FONT = "font-family=\"-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif\""
W = 760
LEFT = 150  # room for row labels
RIGHT = 40
MOTION = """<style>
  .fade { opacity: 0; animation: fade 0.5s ease-out forwards; }
  .grow { transform-box: fill-box; transform-origin: left center; transform: scaleX(0); animation: grow 0.8s ease-out forwards; }
  @keyframes fade { to { opacity: 1; } }
  @keyframes grow { to { transform: scaleX(1); } }
  @media (prefers-reduced-motion: reduce) { .fade, .grow { animation: none; opacity: 1; transform: none; } }
</style>"""

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
    def __init__(self, height: int, theme: dict[str, str], title: str, animated: bool = False):
        self.t = theme
        self.animated = animated
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" viewBox="0 0 {W} {height}" role="img" aria-label="{esc(title)}">',
            f"<title>{esc(title)}</title>",
            *([MOTION] if animated else []),
            f'<rect width="{W}" height="{height}" fill="{theme["surface"]}"/>',
        ]

    def _motion(self, kind: str, delay: float | None) -> str:
        if not self.animated or delay is None:
            return ""
        return f' class="{kind}" style="animation-delay:{delay:.2f}s"'

    def text(self, x: float, y: float, s: str, *, size: int = 13, color: str = "text", anchor: str = "start", weight: int = 400, delay: float | None = None) -> None:
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" fill="{self.t[color]}" text-anchor="{anchor}"{self._motion("fade", delay)}>{esc(s)}</text>'
        )

    def line(self, x1: float, y1: float, x2: float, y2: float, color: str, width: float = 2, delay: float | None = None) -> None:
        self.parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{self.t[color]}" stroke-width="{width}" stroke-linecap="round"{self._motion("fade", delay)}/>'
        )

    def dot(self, x: float, y: float, color: str, r: float = 5, delay: float | None = None) -> None:
        # 2px surface ring keeps overlapping dots apart
        self.parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{self.t[color]}" stroke="{self.t["surface"]}" stroke-width="2"{self._motion("fade", delay)}/>'
        )

    def rect(self, x: float, y: float, w: float, h: float, color: str, radius: float = 4, delay: float | None = None, grow: bool = False) -> None:
        self.parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{h:.1f}" rx="{radius}" fill="{self.t[color]}"{self._motion("grow" if grow else "fade", delay)}/>'
        )

    def done(self) -> str:
        return "\n".join(self.parts + ["</svg>"]) + "\n"


def axis(svg: Svg, top: float, bottom: float, ticks: list[tuple[float, str]], label: str) -> None:
    """Recessive vertical gridlines, tick labels and an axis label underneath."""
    for x, tick in ticks:
        svg.line(x, top, x, bottom, "grid", 1)
        svg.text(x, bottom + 18, tick, size=12, color="muted", anchor="middle")
    svg.text((LEFT + W - RIGHT) / 2, bottom + 40, label, size=12, color="muted", anchor="middle")


def legend(svg: Svg, y: float, items: list[tuple[str, str]]) -> None:
    x = LEFT
    for color, name in items:
        svg.rect(x, y - 10, 12, 12, color, 3)
        svg.text(x + 18, y, name, size=12)
        x += 18 + len(name) * 6.6 + 24


def per_task(name: str, setup: str) -> dict[tuple[str, str], float]:
    costs = load_costs(Path("runs/live") / name / "trace.sqlite")
    out = {}
    for key, row in costs.items():
        s, st, task, injection = key.split(".")
        if st == setup and injection == "none":
            out[(s, task)] = row["cost"]
    return out


def cost_parts(name: str, setup: str) -> tuple[float, float, float]:
    """Mean cost per task: output, uncached input, cached input."""
    conn = sqlite3.connect(Path("runs/live") / name / "trace.sqlite")
    try:
        tasks, out, unc, cac = conn.execute(
            "SELECT count(DISTINCT r.label), sum(k.cost_output), sum(k.cost_uncached_input), sum(k.cost_cached_input)"
            " FROM calls k JOIN runs r ON r.id = k.run_id"
            " WHERE r.id IN (SELECT max(id) FROM runs GROUP BY label) AND r.label LIKE ?",
            (f"%.{setup}.%.none",),
        ).fetchone()
    finally:
        conn.close()
    return out / tasks, unc / tasks, cac / tasks


def fig_cost(theme: dict[str, str], animated: bool = False) -> str:
    """Each task's cost change, Prestige against the guard alone, with the total change and its interval."""
    rows = []
    for label, name in MODELS:
        guard, prestige = per_task(name, "C"), per_task(name, "D")
        keys = sorted(set(guard) & set(prestige))
        changes = [100 * (prestige[k] / guard[k] - 1) for k in keys if guard[k]]
        rows.append((label, cost_change(guard, prestige), changes))
    h = 260
    svg = Svg(h, theme, "Change in cost per task, Prestige against the guard alone", animated)
    lo, hi = -100, 200
    x = lambda v: LEFT + (min(max(v, lo), hi) - lo) / (hi - lo) * (W - LEFT - RIGHT)  # noqa: E731
    top, bottom = 16, 200
    axis(svg, top, bottom, [(x(v), f"{v:+d}%" if v else "0") for v in range(-100, 201, 50)], "Change in cost per task, Prestige against the guard alone")
    svg.line(x(0), top, x(0), bottom, "muted", 1.5)
    rng = random.Random(7)  # fixed jitter so the figure is the same every build
    for i, (label, (change, ci_lo, ci_hi), changes) in enumerate(rows):
        y = top + 58 + i * 92
        svg.text(LEFT - 14, y + 4, label, anchor="end", weight=600)
        svg.rect(x(ci_lo), y - 30, x(ci_hi) - x(ci_lo), 60, "band", 4, delay=1.6)
        for j, c in enumerate(changes):
            jitter = rng.uniform(-22, 22)
            svg.dot(x(c), y + jitter, "prestige", 4, delay=0.02 * j + 0.5 * i)
            if c > hi:  # drawn at the edge, labelled with its real value
                svg.text(x(hi) - 8, y + jitter + 4, f"{c:+.0f}%", anchor="end", size=11, color="muted", delay=1.6)
        svg.line(x(change), y - 34, x(change), y + 34, "text", 2.5, delay=1.8)
        svg.text(x(0) - 8, y - 38, f"{change:+.0f}% (95% CI {ci_lo:+.0f}% to {ci_hi:+.0f}%)", anchor="end", size=12, weight=600, delay=1.8)
    return svg.done()


def fig_breakdown(theme: dict[str, str], animated: bool = False) -> str:
    """Mean cost per task by part, guard only against Prestige, on one dollar scale."""
    parts = (("out", "Output, reasoning included"), ("unc", "Uncached input"), ("cac", "Cached input"))
    h = 270
    svg = Svg(h, theme, "Mean cost per task by part, guard only against Prestige", animated)
    scale = (W - LEFT - RIGHT - 70) / 0.020
    top = 30
    for i, (label, name) in enumerate(MODELS):
        y0 = top + i * 92
        svg.text(LEFT - 14, y0 + 30, label, anchor="end", weight=600)
        for j, (setup, setup_name) in enumerate((("C", "Guard only"), ("D", "Prestige"))):
            y = y0 + j * 34
            values = cost_parts(name, setup)
            svg.text(LEFT + 4, y - 3, setup_name, size=11, color="muted")
            cursor = LEFT
            delay = 0.3 * (2 * i + j)
            for value, (key, _) in zip(values, parts):
                w = value * scale
                svg.rect(cursor, y, w - 2, 20, key, 4, delay=delay, grow=True)
                if w > 52:
                    svg.text(cursor + 6, y + 14, f"${value:.4f}", size=11, weight=600, color="on_" + key, delay=delay + 0.6)
                cursor += w
            svg.text(cursor + 8, y + 14, f"${sum(values):.4f}", size=12, weight=600, delay=delay + 0.6)
    legend(svg, h - 40, [(k, n) for k, n in parts])
    svg.text(LEFT, h - 14, "Mean cost per task, US dollars at list prices", size=12, color="muted")
    return svg.done()


def fig_attacks(theme: dict[str, str], animated: bool = False) -> str:
    """Share of runs where an optimized attack worked, with Wilson intervals."""
    h = 230
    svg = Svg(h, theme, "Optimized attacks that worked: no gateway against Prestige", animated)
    x = lambda p: LEFT + p * (W - LEFT - RIGHT - 120)  # noqa: E731
    top, bottom = 16, 170
    axis(svg, top, bottom, [(x(p / 100), f"{p}%") for p in range(0, 101, 25)], "Runs where the attack worked, with 95% Wilson interval")
    for i, (model, setup, k, n) in enumerate(ATTACKS):
        y = top + 24 + i * 34 + (10 if i >= 2 else 0)
        if setup == "No gateway":
            svg.text(LEFT - 14, y + 21, model, anchor="end", weight=600)
        color = "none" if setup == "No gateway" else "prestige"
        lo, hi = wilson(k, n)
        delay = 0.4 * i
        svg.line(x(lo), y, x(hi), y, color, 2, delay=delay)
        svg.dot(x(k / n), y, color, 6, delay=delay)
        svg.text(x(hi) + 12, y + 4, f"{setup}: {k} of {n}", size=12, delay=delay)
    return svg.done()


def fig_cache(theme: dict[str, str], animated: bool = False) -> str:
    """Uncached input under Prestige, split by cause, one tall segmented bar per model."""
    causes = (("first call", "First call", "c1"), ("new", "New content", "c2"), ("provider miss", "Same prefix, not cached", "c3"))
    rows = []
    for label, name in MODELS:
        row = split(Path("runs/live") / name / "trace.sqlite")["D"]
        uncached = row["input"] - row["cached"]
        rows.append((label, 100 * row["cached"] / row["input"], [100 * row[c] / uncached for c, _, _ in causes]))
    h = 210
    svg = Svg(h, theme, "Uncached input under Prestige, by cause", animated)
    x0, x1 = LEFT, W - RIGHT
    for i, (label, cached, shares) in enumerate(rows):
        y = 24 + i * 64
        svg.text(LEFT - 14, y + 13, label, anchor="end", weight=600)
        svg.text(LEFT - 14, y + 30, f"{cached:.0f}% from cache", anchor="end", size=12, color="muted")
        cursor = x0
        for j, (share, (_, _, color)) in enumerate(zip(shares, causes)):
            w = share / 100 * (x1 - x0)
            delay = 0.5 * i + 0.25 * j
            svg.rect(cursor, y, w - 2, 28, color, 4, delay=delay, grow=True)  # 2px surface gap between blocks
            if w > 44:
                svg.text(cursor + 8, y + 19, f"{share:.0f}%", size=12, weight=600, color="on_" + color, delay=delay + 0.6)
            cursor += w
    legend(svg, h - 40, [(c, n) for _, n, c in causes])
    svg.text(LEFT, h - 14, "Share of uncached input tokens", size=12, color="muted")
    return svg.done()


FIGURES = {"cost": fig_cost, "breakdown": fig_breakdown, "attacks": fig_attacks, "cache": fig_cache}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prestige.eval.figures", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="docs/figures")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, build in FIGURES.items():
        for mode, theme in THEMES.items():
            for animated in (False, True):
                path = out / f"{name}-{mode}{'-animated' if animated else ''}.svg"
                path.write_text(build(theme, animated), encoding="utf-8")
                print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
