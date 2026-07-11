"""Prune finished run directories once their results are safely in S3.

A run's local dir (narration.mp3, output.mp4 backup, scenes, script, etc.) is only
useful until the ClickUp task is filed — after that everything anyone needs lives
in S3 + ClickUp. Keeps the single most recent DONE run for a grace window (default
24h, for "wait, what did that last one look like" debugging); every other DONE run
is deleted immediately. Runs that never finished (no done-marker) are left alone —
this is not a "clean up my mess" tool, just a "stop hoarding shipped runs" one.
"""
import glob
import os
import shutil
import time


def prune_runs(runs_dir: str, done_marker: str, keep_latest_hours: float = 24) -> list[str]:
    """Delete DONE run dirs under `runs_dir` (i.e. containing `done_marker`),
    except the most recently completed one while it's under `keep_latest_hours`
    old. Returns the list of dirs removed."""
    done = []
    for d in glob.glob(os.path.join(runs_dir, "*")):
        marker = os.path.join(d, done_marker)
        if os.path.isdir(d) and os.path.exists(marker):
            done.append((os.path.getmtime(marker), d))
    if not done:
        return []

    done.sort(key=lambda t: t[0], reverse=True)   # newest first
    (latest_ts, latest_dir), rest = done[0], done[1:]

    removed = []
    for _, d in rest:                              # never the newest — always prune
        shutil.rmtree(d)
        removed.append(d)
    if time.time() - latest_ts > keep_latest_hours * 3600:
        shutil.rmtree(latest_dir)
        removed.append(latest_dir)
    return removed


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        sys.exit("usage: cleanup.py <runs_dir> <done_marker_filename> [keep_latest_hours]")
    removed = prune_runs(sys.argv[1], sys.argv[2],
                         float(sys.argv[3]) if len(sys.argv) > 3 else 24)
    print(f"pruned {len(removed)} run dir(s): {removed}" if removed else "nothing to prune")
