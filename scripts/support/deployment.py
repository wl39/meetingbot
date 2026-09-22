"""Replace owned Python source trees while the corresponding service is stopped."""
import shutil
import tempfile
from pathlib import Path


def replace_code_tree(source: Path, destination: Path):
    """Stage all source first, remove obsolete modules, and restore on swap failure.

    Callers verify deployment ownership and stop the service. This only accepts
    application code directories; data, model caches and environments stay outside.
    """
    source, destination = Path(source), Path(destination)
    if not source.is_dir() or source.is_symlink() or destination.is_symlink():
        raise ValueError("Expected real application source directories")
    if destination.exists() and not destination.is_dir():
        raise ValueError("Deployment destination must be a directory")
    if source.resolve() == destination.resolve():
        raise ValueError("Source and deployment must be separate")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{destination.name}-deploy-", dir=destination.parent) as temporary:
        staged, previous = Path(temporary) / "next", Path(temporary) / "previous"
        shutil.copytree(source, staged, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if destination.exists():
            destination.replace(previous)
        try:
            staged.replace(destination)
        except BaseException:
            if previous.exists():
                previous.replace(destination)
            raise
