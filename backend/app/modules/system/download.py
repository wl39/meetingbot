"""Executed in an isolated engine environment by the authenticated runtime manager."""
import json
import sys
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

# Resolve a commit before downloading so the manifest records the exact revision.
repo, cache, result = sys.argv[1:]
revision = HfApi().model_info(repo).sha
path = snapshot_download(repo_id=repo, revision=revision, cache_dir=cache)
Path(result).write_text(json.dumps({"repo": repo, "revision": revision, "path": path}), encoding="utf-8")
