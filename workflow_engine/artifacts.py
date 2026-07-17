import hashlib
from pathlib import Path


def snapshot_project(root):
    root = Path(root).resolve()
    snapshot = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == ".matlab-agent":
            continue
        if "__pycache__" in relative.parts:
            continue
        try:
            stat = path.stat()
            snapshot[relative.as_posix()] = (stat.st_size, stat.st_mtime_ns)
        except OSError:
            pass
    return snapshot


def _record(root, relative):
    path = Path(root) / relative
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    extension = path.suffix.lower()
    kinds = {
        ".png": "image", ".jpg": "image", ".jpeg": "image", ".fig": "figure",
        ".mat": "matlab_data", ".csv": "table", ".xlsx": "table", ".wav": "audio",
        ".mp4": "video", ".slx": "simulink_model", ".mdl": "simulink_model", ".mlapp": "matlab_app",
        ".pdf": "report", ".md": "report", ".html": "report",
    }
    return {"path": relative, "bytes": path.stat().st_size, "sha256": digest.hexdigest(), "extension": extension, "kind": kinds.get(extension, "file")}


def collect_changes(root, before):
    after = snapshot_project(root)
    created = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    modified = sorted(path for path in set(after) & set(before) if after[path] != before[path])
    records = [_record(root, path) for path in created + modified]
    return {"created": created, "modified": modified, "deleted": deleted, "artifacts": records}
