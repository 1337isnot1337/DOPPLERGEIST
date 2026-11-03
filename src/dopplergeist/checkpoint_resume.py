"""Upgrade the known pre-batching save without changing its scoring arithmetic."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from importlib.metadata import version
from pathlib import Path
import platform
import shutil
import sqlite3
import uuid

from .data_access import content_hash, write_json


# Scoring implementation of 225bf6b, including the old first-group batch rule.
# Other saved implementations retain the ordinary strict resume checks.
LEGACY_SOURCES = {
    "matching.py": "1a0df93bd2ab9bf67253680d0933d5900eb2b5e4ba9346f17c8180565922cc6c",
    "search.py": "d7927fd0e0a5373c45be16812bbd29439d66a225eb8c8e744ced65158f4a9f09",
    "batch_ridge.py": "0042a55f576d385f39aeec9f3cbbfa14ffa70a58283437b14530cfb72d58a59f",
    "geometry.py": "71ea6ca7402ae91a55efdb0f8a307d10b80f8218350f077fecaa850523c1ce41",
    "tiled_search.py": "cd6eccc357241c1eec0f1d800f3aea3a2691b74b2736625da44ebe4686f15150",
    "acoustic_screen.py": "fc17f54913c066a2dedfd0a9ed0699cf9f93d0a72cb2c5a89e7803542a207d95",
    "finite_search.py": "78ed9fca6cb13c9754ea0f4438f1bb54bbcdc488ead2a4d77a15f149b6d77b1c",
}


def upgrade_legacy_job(directory):
    """Prepare a replacement search before swapping it into a stopped job.

    Completed payloads and retention records stay unchanged. The old directory
    and audio/operator identities remain available for rollback. New work uses
    staged batching with the saved first-group arithmetic and fallback checks.
    """
    from .automatic import _audio_identity, _digest
    from . import geometry, matching, native_cpa

    directory = Path(directory)
    search = directory / "search"
    if not (search / "manifest.json").exists():
        return None
    manifest = json.loads((search / "manifest.json").read_text())
    old = manifest["configuration"]
    if any(old["code"].get(name) != digest for name, digest in LEGACY_SOURCES.items()):
        return None
    if getattr(matching, "_native_fit_irls", None) is not None:
        raise ValueError("Legacy checkpoint continuation requires the Python ridge fitter")
    if geometry.ACOUSTIC_BACKEND != "python-acoustic-v1":
        raise ValueError("Legacy checkpoint continuation requires the Python acoustic solver")
    if native_cpa.CPA_BACKEND != "python-cpa-v1":
        raise ValueError("Legacy checkpoint continuation requires Python closest-approach processing")
    if (old["scoring"].get("mode") != "robust_ridge" or old.get("coarse_floor_policy") != "per_tile"
            or old["scoring"].get("time_origin") is not None
            or old.get("filters", {}).get("association") != "subsets"):
        raise ValueError("This legacy checkpoint mode has no compatible upgrade")
    runtime = {"python": platform.python_version(), "machine": platform.machine(),
               "packages": {name: version(name) for name in old["runtime"]["packages"]}}
    if runtime != old["runtime"]:
        raise ValueError("Saved search runtime changed; the legacy arithmetic requires its original runtime")
    state = json.loads((directory / "result.json").read_text())
    if state["status"] not in {"cancelled", "failed", "inconclusive"}:
        raise ValueError("Stop the previous job before upgrading its checkpoints")
    request = json.loads((directory / "request.json").read_text())
    operator = json.loads((directory / "operator.json").read_text())
    audio = json.loads((directory / "resume.json").read_text())
    identity = _audio_identity(request, operator)
    for key in set(audio["identity"]) | set(identity):
        if key != "modules" and audio["identity"].get(key) != identity.get(key):
            raise ValueError("Saved audio, request, settings or runtime changed")
    if any(_digest(directory / name) != digest for name, digest in audio["files"].items()):
        raise ValueError("Saved audio checkpoint changed")
    discovery = json.loads((directory / "discovery/discovery.json").read_text())
    events, _ = matching.prepare_events(discovery["events"])
    if events != old["events"]:
        raise ValueError("Prepared events no longer match the saved search")
    current = deepcopy(old)
    from .provenance import implementation_files
    package_root = Path(__file__).parent
    current["code"] = {p.relative_to(package_root).as_posix(): _digest(p)
                       for p in implementation_files(package_root, recursive=False)}
    current["scoring"]["legacy_first_batch"] = True
    new_hash = content_hash(current)
    suffix = uuid.uuid4().hex[:12]
    staged = directory / f".search-upgrade-{suffix}"
    previous = directory / f"search-before-upgrade-{suffix}"
    backup = directory / f"checkpoint-upgrade-{suffix}"
    backup.mkdir()
    for name in ("resume.json", "operator.json", "result.json", "provenance.json"):
        if (directory / name).exists():
            shutil.copy2(directory / name, backup / name)

    def ignore(path, names):
        return [name for name in names if name == ".tile-workers" or name.endswith(".tmp")
                or name.startswith("retention.sqlite")]

    # JSON/support files are immutable until atomically replaced. Hard links
    # retain their original bytes without copying the whole saved search twice.
    shutil.copytree(search, staged, copy_function=lambda src, dst: Path(dst).hardlink_to(src), ignore=ignore)
    with sqlite3.connect((search / "retention.sqlite").resolve().as_uri() + "?mode=ro", uri=True) as source:
        if source.execute("SELECT identity FROM run").fetchone() != (manifest["run_hash"],):
            raise ValueError("Saved retention ledger identity differs from its manifest")
        with sqlite3.connect(staged / "retention.sqlite") as target:
            source.backup(target)
            target.execute("UPDATE run SET identity=?", (new_hash,))
    # Keep saved payloads and their producer identity byte-for-byte. The search
    # reader accepts this one explicitly compatible producer and still checks
    # each payload and retention stage before reuse.
    tiles = len(list(staged.glob("tile-*.json")))
    write_json(staged / "manifest.json", {"run_hash": new_hash, "configuration": current})
    report = {"version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
              "old_run_hash": manifest["run_hash"], "new_run_hash": new_hash,
              "tiles_preserved": tiles, "legacy_first_batch": True,
              "previous_search": str(previous), "identity_backup": str(backup)}
    write_json(backup / "upgrade.json", report)
    search.rename(previous)
    try:
        staged.rename(search)
        audio["identity"] = identity
        operator["resume_legacy_first_batch"] = True
        write_json(directory / "resume.json", audio)
        write_json(directory / "operator.json", operator)
        write_json(directory / "checkpoint-upgrade.json", report)
    except BaseException:
        # No worker has been launched yet. Restore the original save if the
        # directory/identity commit cannot finish.
        if search.exists():
            search.rename(staged)
        previous.rename(search)
        for name in ("resume.json", "operator.json"):
            shutil.copy2(backup / name, directory / name)
        raise
    return report


def compatible_checkpoint_runs(output, run_hash):
    """Accept the validated legacy producer only for this exact upgraded run."""
    accepted = {run_hash}
    path = Path(output).parent / "checkpoint-upgrade.json"
    if path.exists():
        report = json.loads(path.read_text())
        if (report.get("version") == 1 and report.get("new_run_hash") == run_hash
                and report.get("legacy_first_batch") is True):
            accepted.add(report["old_run_hash"])
    return accepted
