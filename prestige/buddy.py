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
import queue
import re
import shlex
import sqlite3
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from prestige import approvals

DEFAULT_DB = "runs/prestige.sqlite"

# A little buddy in a hood, with its face peeking out. Every line is the same width.
def _face(eyes: str, mouth: str) -> list[str]:
    return ["    " + row for row in [
        "      .-~~~~~-.      ",
        "    .'         '.    ",
        "   /  .-------.  \\   ",
        f"   |  ({eyes})  |   ",
        f"   |  ({mouth})  |   ",
        "   |  '-------'  |   ",
        "  /|             |\\  ",
        " ( |             | ) ",
        "  '~~~~~~~~~~~~~~~'  ",
    ]]  # shifted right so the cheer's arms fit


FACES = {
    "idle": _face(" o   o ", "*  u  *"),
    "blink": _face(" -   - ", "*  u  *"),
    "look": _face("  o   o", "*  u  *"),
    "alarm": _face(" O   O ", "*  o  *"),
    "stern": _face(" >   < ", "   -   "),
    "happy": _face(" ^   ^ ", "*  w  *"),
    # Both arms up, eyes shut, all done.
    "cheer": [
        "          .-~~~~~-.          ",
        "  o     .'         '.     o  ",
        "   \\   /  .-------.  \\   /   ",
        "    \\  |  ( ^   ^ )  |  /    ",
        "     \\ |  (*  w  *)  | /     ",
        "      \\|  '-------'  |/      ",
        "       |             |       ",
        "       |             |       ",
        "      '~~~~~~~~~~~~~~~'      ",
    ],
}

COLORS = {"idle": "37", "blink": "37", "look": "37", "alarm": "31", "stern": "33", "happy": "32", "cheer": "32"}
NAME = "Muse"

HELP = """commands
  demo [user_task injection_task]   hijacked banking task, guard off then on. Offline, no spend
  results                           headline numbers from the README
  watch [--db PATH] [--cap USD]     follow guard events live while `serve` runs. Ctrl+C to stop
  spend [--db PATH] [--cap USD]     calls, tokens and cost in a trace database
  cap USD                           the spend cap to show under me. Match serve's --max-total
  serve                             the command to start the gateway in another window
  help, quit"""


class Sprite:
    def __init__(self, out=None, animate: bool | None = None, color: bool | None = None):
        self.out = out or sys.stdout
        self.db: str | None = None  # set while watching, so every message shows the spend
        self.cap: float | None = None
        self.model: str | None = None  # the model behind the gateway, shown under the name
        tty = hasattr(self.out, "isatty") and self.out.isatty()
        self.animate = tty if animate is None else animate
        self.color = (tty and not os.environ.get("NO_COLOR")) if color is None else color
        if self.color and os.name == "nt":
            os.system("")  # turns on ANSI colors in the Windows console

    def say(self, mood: str, text: str) -> int:
        """Prints the face, then the text under it. Returns how many lines that took."""
        face = [line.rstrip() for line in FACES[mood]]
        lines = text.splitlines() or [""]
        money = self.money()
        if money:
            lines.append(money)
        paint = (lambda s, c=COLORS[mood]: f"\033[{c}m{s}\033[0m") if self.color else (lambda s, c="": s)
        for line in face:
            self.out.write(paint(line) + "\n")
        width = len(FACES["cheer"][0])
        self.out.write(paint(NAME.center(width).rstrip(), "1") + "\n")
        if self.model:
            self.out.write(paint(self.model.center(width).rstrip(), "90") + "\n")
        for i, line in enumerate(lines):
            dim = money and i == len(lines) - 1  # the spend line is grey
            self.out.write((paint("  " + line, "90") if dim else "  " + line) + "\n")
        self.out.write("\n")
        self.out.flush()
        return len(face) + 1 + bool(self.model) + len(lines) + 1

    def money(self) -> str:
        """Spend so far against the cap, when a trace database is set."""
        if not self.db or not Path(self.db).is_file():
            return ""
        spent = _spent(self.db)
        if self.cap:
            return f"${spent:.2f} spent of ${self.cap:.2f} cap, ${max(self.cap - spent, 0):.2f} left"
        return f"${spent:.2f} spent, no cap shown. Use cap USD"

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
    try:
        from prestige.eval.replay import replay
    except ImportError:
        sprite.say("look", "The demo needs the benchmark. Install it with\npip install \"prestige[security]\"")
        return 1

    sprite.model = "scripted agent"
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
            blocks = [f"{tool}.{arg}, its value came only from {source}" for action, rule, tool, arg, source in o.events if action == "blocked"]
            text = "Guard on.\n" + "\n".join(f"blocked {b}" for b in blocks) + f"\nAttack {'worked' if o.security else 'failed'}."
            sprite.wiggle(["stern", "happy"] if not o.security else ["alarm"], text)
    live = _headline()
    sprite.wiggle(["happy", "cheer"], "All done. The attacker got nothing.\n$0.00 spent, it ran offline." + (f"\nLive, Prestige cut cost per task {live}." if live else ""))
    sprite.model = None
    return 0


def _readme(readme: str | Path = "README.md") -> str:
    """The repo's README, or the copy installed with the package."""
    path = Path(readme)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    try:
        from importlib.metadata import metadata

        return metadata("prestige").get_payload() or ""
    except Exception:  # not installed as a package
        return ""


def results(sprite: Sprite, readme: str | Path = "README.md") -> int:
    text = _readme(readme)
    if "## Results" not in text:
        sprite.say("look", "I can't find the results. Run me from the repo folder.")
        return 1
    rows = []
    for line in text.split("## Results", 1)[-1].split("\n## ", 1)[0].splitlines():
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
        calls, tokens, cached = conn.execute(
            "SELECT count(*), coalesce(sum(input_tokens), 0), coalesce(sum(cached_input_tokens), 0) FROM calls"
        ).fetchone()
        blocked = _count(conn, "SELECT count(*) FROM guard_events WHERE action = 'blocked'")
    finally:
        conn.close()
    share = f"{100 * cached / tokens:.0f}%" if tokens else "none"
    before, sprite.db, sprite.model = sprite.db, db, _model(db)
    sprite.say("idle", f"{calls} model calls.\nInput from cache: {share}.\nGuard blocks: {blocked}.")
    cheer(sprite, db)
    sprite.db, sprite.model = before, None
    return 0


def watch(sprite: Sprite, db: str = DEFAULT_DB, poll: float = 1.0, stop: Callable[[], bool] = lambda: False, ask: Callable | None = None) -> int:
    """Follows guard events as they land, and answers questions from `serve --ask`. Only events newer
    than when it started."""
    if not Path(db).is_file():
        sprite.say("look", f"Waiting for {db}.\nStart `python -m prestige serve` first.")
    while not Path(db).is_file():
        if stop():
            return 1
        time.sleep(max(poll, 1.0))
    ask = ask or ask_while_open
    conn = approvals.connect(db)
    last = _count(conn, "SELECT coalesce(max(id), 0) FROM guard_events")
    sprite.db, sprite.model = db, _model(db)
    sprite.say("idle", f"Watching {db}.\nCtrl+C to stop.")
    try:
        while not stop():
            for row_id, rule, tool, arg, source, value in approvals.pending(conn):
                still_open = lambda row=row_id: approvals.is_pending(conn, row)  # noqa: E731
                yes = question(sprite, rule, f"{tool}.{arg}" if arg else tool, source, value, ask, still_open)
                if yes is None or not approvals.answer(conn, row_id, yes):
                    sprite.say("look", "Too late. It timed out, so it was blocked.")
                else:
                    sprite.say("idle" if yes else "happy", "OK, it goes through." if yes else "Blocked it.")
            rows = _rows(conn, last)
            for row_id, action, rule, tool, arg, source in rows:
                last = row_id
                sprite.model = sprite.model or _model(db)
                target = f"{tool}.{arg}" if arg else tool
                if action == "blocked":
                    sprite.wiggle(["alarm", "stern"], f"Blocked {target}.\nIts value came only from {source}.")
                elif action == "confirmed":
                    sprite.say("look", f"Asked the user about {target}. They said yes.")
                else:
                    sprite.say("look", f"Flagged {target}. Only {source} asked for it.")
            time.sleep(poll)
    except KeyboardInterrupt:
        pass
    finally:
        conn.close()
    cheer(sprite, db, "Done watching.")
    sprite.db, sprite.model = None, None
    return 0


def question(sprite: Sprite, rule: str, target: str, source: str, value: str | None, ask: Callable, still_open: Callable[[], bool]) -> bool | None:
    """Asks the person at the terminal. Anything but y is a no. None when the gateway stopped waiting."""
    sprite.wiggle(["alarm", "look"], f"The agent wants to run {target}\nwith {value!r}.\nThat value came only from {source}, never from you.")
    try:
        reply = ask("  Let it through? [y/N] ", still_open)
    except EOFError:
        return False
    return None if reply is None else reply.strip().lower() in ("y", "yes")


_lines: queue.Queue[str | None] = queue.Queue()  # None: stdin closed
_reader: threading.Thread | None = None


def _read_lines() -> None:
    for line in sys.stdin:
        _lines.put(line)
    _lines.put(None)


def ask_while_open(prompt: str, still_open: Callable[[], bool], fresh: bool = True) -> str | None:
    """Like input(), but gives up when the question closes. None when it did.

    One thread reads whole lines from stdin, so typing works the way it does at any shell prompt,
    in every terminal. With `fresh`, lines typed before the question showed up are thrown away, so a
    stray keypress can't approve a call.
    """
    global _reader
    if _reader is None:
        _reader = threading.Thread(target=_read_lines, daemon=True)
        _reader.start()
    while fresh and not _lines.empty():
        if _lines.get_nowait() is None:
            raise EOFError
    sys.stdout.write(prompt)
    sys.stdout.flush()
    while still_open():
        try:
            line = _lines.get(timeout=0.2)
        except queue.Empty:
            continue
        if line is None:
            raise EOFError
        return line
    sys.stdout.write("\n")
    return None


def cheer(sprite: Sprite, db: str, first: str = "All done.") -> None:
    """The end pose: arm up, with what the cache saved and what the guard stopped."""
    saved, blocked = _saved(db), _blocks(db)
    before, sprite.db = sprite.db, db
    sprite.wiggle(["happy", "cheer"], f"{first}\nSaved by the prompt cache: ${saved:.2f}.\nCalls the guard stopped: {blocked}.")
    sprite.db = before


def _model(db: str) -> str | None:
    conn = sqlite3.connect(db)
    try:
        row = conn.execute("SELECT model FROM calls ORDER BY id DESC LIMIT 1").fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def _saved(db: str) -> float:
    """What the cached tokens would have cost at the full input rate, minus what they did cost."""
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT coalesce(sum(cached_input_tokens * (price_input - price_cached_input)), 0) / 1e6 FROM calls").fetchone()[0]
    except sqlite3.OperationalError:
        return 0.0
    finally:
        conn.close()


def _blocks(db: str) -> int:
    conn = sqlite3.connect(db)
    try:
        return _count(conn, "SELECT count(DISTINCT run_id || ':' || coalesce(call_id, '')) FROM guard_events WHERE action = 'blocked'")
    finally:
        conn.close()


def _headline(readme: str | Path = "README.md") -> str:
    """The cost cut on each model, from the README's results table."""
    for line in _readme(readme).splitlines():
        cells = [re.sub(r"\s*\(.*?\)", "", c).strip().replace("**", "") for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0] == "Change":
            return f"{cells[1].lstrip('-')} on Muse Spark and {cells[2].lstrip('-')} on Spark Open"
    return ""


def _spent(db: str) -> float:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT coalesce(sum(cost_uncached_input + cost_cached_input + cost_output), 0) FROM calls").fetchone()[0]
    except sqlite3.OperationalError:  # no calls yet
        return 0.0
    finally:
        conn.close()


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


def _option(words: list[str], flag: str) -> str | None:
    if flag in words and words.index(flag) + 1 < len(words):
        return words[words.index(flag) + 1]
    return None


def run(sprite: Sprite, words: list[str]) -> int | None:
    """One command. Returns an exit code, or None for quit."""
    if not words:
        return 0
    cmd, rest = words[0].lower(), words[1:]
    db = _option(rest, "--db") or DEFAULT_DB
    cap = _option(rest, "--cap") or (rest[0] if cmd == "cap" and rest else None)
    if cap:
        try:
            sprite.cap = float(cap.lstrip("$"))
        except ValueError:
            sprite.say("look", f"`{cap}` isn't a dollar amount.")
            return 2
    if cmd in ("quit", "exit", "q"):
        return None
    if cmd == "cap":
        sprite.say("idle", f"Cap set to ${sprite.cap:.2f}." if sprite.cap else "No cap set. Try cap 5")
        return 0
    if cmd == "demo":
        return demo(sprite, *rest[:2])
    if cmd == "results":
        return results(sprite)
    if cmd == "spend":
        return spend(sprite, db)
    if cmd == "watch":
        return watch(sprite, db)
    if cmd == "serve":
        sprite.say("idle", "In another window:\npython -m prestige serve --labels banking --muse \\\n  --policies cache,reason --max-total 5 --max-per-conversation 0.50\n--max-total stops everything at $5. --max-per-conversation stops one agent at $0.50.\nThen `watch --cap 5` here.")
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
            line = ask_while_open("\nprestige> ", lambda: True, fresh=False)
        except (EOFError, KeyboardInterrupt):
            break
        try:
            if run(sprite, shlex.split(line)) is None:
                break
        except Exception as exc:  # keep the session alive
            sprite.say("alarm", f"That failed: {type(exc).__name__}.")
    sprite.wiggle(["happy", "cheer"], "Bye.")
    return 0
