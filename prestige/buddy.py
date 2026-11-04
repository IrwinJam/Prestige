"""A small sprite in the terminal that runs Prestige for you.

    python -m prestige buddy               # interactive
    python -m prestige buddy demo          # one command, then exit
    python -m prestige buddy watch --db runs/prestige.sqlite

Run `python -m prestige serve` in another window, point your agent at it, then `watch` here. The sprite
reacts to every call the guard blocks. It reads the trace database only and never spends anything.
Guard events hold a hash, so it never shows a blocked value either.
"""

from __future__ import annotations

import contextlib
import os
import re
import shlex
import sqlite3
import sys
import time
from collections.abc import Callable
from pathlib import Path

DEFAULT_DB = "runs/prestige.sqlite"

# A round face in a fuzzy hood. Every line is the same width so the speech bubble lines up.
def _face(eyes: str, mouth: str) -> list[str]:
    return [
        "    .~~~~~~~~~.    ",
        "  .~           ~.  ",
        " (   .-------.   ) ",
        f" (  |{eyes}|  ) ",
        f" (  |{mouth}|  ) ",
        "  ~. '-------' .~  ",
        "    '~~~~~~~~~'    ",
    ]


FACES = {
    "idle": _face("  o   o  ", " '  u  ' "),
    "blink": _face("  -   -  ", " '  u  ' "),
    "look": _face("   o   o ", " '  u  ' "),
    "alarm": _face("  O   O  ", " '  o  ' "),
    "stern": _face("  >   <  ", "    -    "),
    "happy": _face("  ^   ^  ", " '  w  ' "),
}

COLORS = {"idle": "35", "blink": "35", "look": "35", "alarm": "31", "stern": "33", "happy": "32"}

HELP = """commands
  demo [user_task injection_task]   hijacked banking task, guard off then on. Offline, no spend
  results                           headline numbers from the README
  watch [--db PATH]                 follow guard events live while `serve` runs. Ctrl+C to stop
  spend [--db PATH]                 calls, tokens and cost in a trace database
  serve                             the command to start the gateway in another window
  help, quit"""


class Sprite:
    def __init__(self, out=None, animate: bool | None = None, color: bool | None = None):
        self.out = out or sys.stdout
        tty = hasattr(self.out, "isatty") and self.out.isatty()
        self.animate = tty if animate is None else animate
        self.color = (tty and not os.environ.get("NO_COLOR")) if color is None else color
        if self.color and os.name == "nt":
            os.system("")  # turns on ANSI colors in the Windows console

    def say(self, mood: str, text: str) -> int:
        """Prints the face, then the text under it. Returns how many lines that took."""
        face = [line.rstrip() for line in FACES[mood]]
        lines = text.splitlines() or [""]
        paint = (lambda s: f"\033[{COLORS[mood]}m{s}\033[0m") if self.color else (lambda s: s)
        for line in face:
            self.out.write(paint(line) + "\n")
        for line in lines:
            self.out.write("  " + line + "\n")
        self.out.write("\n")
        self.out.flush()
        return len(face) + len(lines) + 1

    def wiggle(self, moods: list[str], text: str, delay: float = 0.25) -> None:
        """A short animation in place. Skipped when output isn't a terminal."""
        if not self.animate:
            self.say(moods[-1], text)
            return
        rows = 0
        for mood in moods:
            if rows:
                self.out.write(f"\033[{rows}F\033[J")  # back up over the last frame
            rows = self.say(mood, text)
            time.sleep(delay)


def demo(sprite: Sprite, user_task: str = "user_task_0", injection_task: str = "injection_task_0") -> int:
    from prestige.eval.replay import replay

    sprite.wiggle(["idle", "look", "idle"], f"Banking {user_task} with {injection_task} placed.\nScripted agent, no model, no spend.")
    root = Path("runs/demo")
    root.mkdir(parents=True, exist_ok=True)
    # AgentDojo prints every message, tool output included. It goes to a file under runs/.
    with open(root / "console.log", "w", encoding="utf-8") as log, contextlib.redirect_stdout(log):
        outcomes = replay(["banking"], root, {user_task}, {injection_task}, ["v3"])
    for o in outcomes:
        if o.scenario != "hijacked":
            continue
        if o.labels is None:
            sprite.wiggle(["look", "alarm"], f"Guard off. Attack {'worked' if o.security else 'failed'}.")
        else:
            blocks = [f"{tool}.{arg}: {rule}, from {source}" for action, rule, tool, arg, source in o.events if action == "blocked"]
            text = "Guard on.\n" + "\n".join(f"blocked {b}" for b in blocks) + f"\nAttack {'worked' if o.security else 'failed'}."
            sprite.wiggle(["stern", "happy"] if not o.security else ["alarm"], text)
    return 0


def results(sprite: Sprite, readme: str | Path = "README.md") -> int:
    path = Path(readme)
    if not path.is_file():
        sprite.say("look", "No README.md here. Run me from the repo folder.")
        return 1
    rows = []
    for line in path.read_text(encoding="utf-8").split("## Results", 1)[-1].split("\n## ", 1)[0].splitlines():
        cells = [re.sub(r"\s*\(.*?\)", "", c).strip().replace("**", "") for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) == 3 and cells[0] and not set(cells[1]) <= set("-:"):
            rows.append(f"{cells[0]:<52} {cells[1]:>10}  {cells[2]:>10}")
    sprite.say("happy", "Live results. Spark on the left, Spark Open on the right.")
    sprite.out.write("\n".join(rows) + "\n\nFull numbers: docs/RESULTS.md\n")
    return 0


def spend(sprite: Sprite, db: str = DEFAULT_DB) -> int:
    if not Path(db).is_file():
        sprite.say("look", f"No trace database at {db} yet.")
        return 1
    conn = sqlite3.connect(db)
    try:
        calls, tokens, cached, cost = conn.execute(
            "SELECT count(*), coalesce(sum(input_tokens), 0), coalesce(sum(cached_input_tokens), 0),"
            " coalesce(sum(cost_uncached_input + cost_cached_input + cost_output), 0) FROM calls"
        ).fetchone()
        blocked = _count(conn, "SELECT count(*) FROM guard_events WHERE action = 'blocked'")
    finally:
        conn.close()
    share = f"{100 * cached / tokens:.0f}%" if tokens else "none"
    sprite.say("idle", f"{calls} model calls, ${cost:.2f} spent.\nInput from cache: {share}.\nGuard blocks: {blocked}.")
    return 0


def watch(sprite: Sprite, db: str = DEFAULT_DB, poll: float = 1.0, stop: Callable[[], bool] = lambda: False) -> int:
    """Follows guard events as they land. Only events newer than when it started."""
    if not Path(db).is_file():
        sprite.say("look", f"Waiting for {db}.\nStart `python -m prestige serve` first.")
    while not Path(db).is_file():
        if stop():
            return 1
        time.sleep(max(poll, 1.0))
    conn = sqlite3.connect(db)
    last = _count(conn, "SELECT coalesce(max(id), 0) FROM guard_events")
    sprite.say("idle", f"Watching {db}.\nCtrl+C to stop.")
    try:
        while not stop():
            rows = _rows(conn, last)
            for row_id, action, rule, tool, arg, source in rows:
                last = row_id
                target = f"{tool}.{arg}" if arg else tool
                if action == "blocked":
                    sprite.wiggle(["alarm", "stern"], f"Blocked {target}.\n{rule}: the value only came from {source}.")
                elif action == "confirmed":
                    sprite.say("look", f"Asked the user about {target}. They said yes.")
                else:
                    sprite.say("look", f"Flagged {target}. {rule}, from {source}.")
            time.sleep(poll)
    except KeyboardInterrupt:
        pass
    finally:
        conn.close()
    sprite.say("blink", "Done watching.")
    return 0


def _count(conn: sqlite3.Connection, sql: str) -> int:
    try:
        return conn.execute(sql).fetchone()[0]
    except sqlite3.OperationalError:  # no guard table yet
        return 0


def _rows(conn: sqlite3.Connection, after: int) -> list[tuple]:
    try:
        return conn.execute("SELECT id, action, rule, tool, arg, source FROM guard_events WHERE id > ? ORDER BY id", (after,)).fetchall()
    except sqlite3.OperationalError:
        return []


def run(sprite: Sprite, words: list[str]) -> int | None:
    """One command. Returns an exit code, or None for quit."""
    if not words:
        return 0
    cmd, rest = words[0].lower(), words[1:]
    db = rest[rest.index("--db") + 1] if "--db" in rest and rest.index("--db") + 1 < len(rest) else DEFAULT_DB
    if cmd in ("quit", "exit", "q"):
        return None
    if cmd == "demo":
        return demo(sprite, *rest[:2])
    if cmd == "results":
        return results(sprite)
    if cmd == "spend":
        return spend(sprite, db)
    if cmd == "watch":
        return watch(sprite, db)
    if cmd == "serve":
        sprite.say("idle", "In another window:\npython -m prestige serve --labels banking --muse \\\n  --policies cache,reason --max-total 5\nThen `watch` here.")
        return 0
    if cmd != "help":
        sprite.say("look", f"I don't know `{cmd}`.")
    sprite.out.write(HELP + "\n")
    return 0 if cmd == "help" else 2


def main(argv: list[str]) -> int:
    sprite = Sprite()
    if argv:
        return run(sprite, argv) or 0
    sprite.wiggle(["blink", "idle"], "Hi. I watch your agent's tool calls.\nType help to see what I can do.")
    while True:
        try:
            line = input("\nprestige> ")
        except (EOFError, KeyboardInterrupt):
            break
        try:
            if run(sprite, shlex.split(line)) is None:
                break
        except Exception as exc:  # keep the session alive
            sprite.say("alarm", f"That failed: {type(exc).__name__}.")
    sprite.say("blink", "Bye.")
    return 0
