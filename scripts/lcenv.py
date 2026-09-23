#!/usr/bin/env python3
"""Where the project lives, when the tools do not live inside it.

In the original kit every tool was copied into `<project>/edit/`, so
`Path(__file__).parent` WAS the edit directory and each script could anchor
itself on its own location. In a plugin the tools sit in one shared place and
the project is somewhere else entirely, so that anchor has to move.

The `lc` wrapper exports `LC_EDIT_DIR` before running anything, and that wins.
The fallbacks keep a tool working when it is run directly:

  1. `$LC_EDIT_DIR`, set by `lc`.
  2. The script's own directory, IF it looks like an edit dir. This is the old
     copied-into-the-project layout, which still works unchanged.
  3. The current directory, which is what "run it from the edit dir" means.

A tool reads the SOURCE VIDEO from `edit_dir.parent`, so the project layout is
fixed: `<project>/take1.mov` beside `<project>/edit/`.
"""
import os
from pathlib import Path

MARKERS = ("transcripts", "cutlist.py", "edl.json", "project.json")


def looks_like_edit_dir(p: Path) -> bool:
    return any((p / m).exists() for m in MARKERS)


def edit_dir(script_file: str) -> Path:
    v = os.environ.get("LC_EDIT_DIR")
    if v:
        return Path(v).resolve()
    here = Path(script_file).resolve().parent
    if looks_like_edit_dir(here):
        return here
    return Path.cwd().resolve()


def project_config(edit: Path) -> dict:
    """`project.json` from the edit dir, or {} when the project has none.

    Every caller supplies its own default for every key it reads, so a missing
    file behaves exactly like an empty one.
    """
    import json
    f = Path(edit) / "project.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text())
    except Exception as e:
        raise SystemExit(f"{f} is not valid JSON: {e}")


_SAFE = None


def filter_safe_path(p) -> str:
    """A path that can sit inside an ffmpeg filter argument, whatever its name.

    A filter string treats ' : , [ ] ; and \\ as syntax, and inside single quotes
    it has no working escape for ' at all, so a project under "Mo's Lessons"
    could not burn its captions. Rather than escape for two parsing levels, a
    path with anything unusual in it is reached through a symlink with a plain
    name in a private temp dir, removed when the process exits.
    """
    import atexit
    import re
    import shutil
    import tempfile
    global _SAFE
    s = str(Path(p).resolve())
    if re.fullmatch(r"[A-Za-z0-9/._+-]+", s):
        return s
    if _SAFE is None:
        _SAFE = Path(tempfile.mkdtemp(prefix="lesson-cut-"))
        atexit.register(shutil.rmtree, _SAFE, True)
    link = _SAFE / f"f{len(list(_SAFE.iterdir()))}{Path(s).suffix}"
    link.symlink_to(s)
    return str(link)
