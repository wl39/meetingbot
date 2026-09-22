"""Explicit download step. Inference workers use local paths and offline mode."""
import argparse
import getpass
import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--asr", choices=["small", "large-v3-turbo"], default="small",
                           help="Prepare an MLX model for Apple Silicon (default: small)")
    selection.add_argument("--diarization-only", action="store_true",
                           help="Prepare only Community-1; works with any installed speech engine")
    parser.add_argument("--diarization", action="store_true", help="Also prepare Community-1")
    parser.add_argument("--prompt-token", action="store_true",
                        help="Read the Community-1 Hugging Face token privately without saving it")
    args = parser.parse_args(argv)
    if args.prompt_token and not (args.diarization or args.diarization_only):
        parser.error("--prompt-token requires --diarization or --diarization-only")
    load_dotenv(ROOT / ".env")
    os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
    token = getpass.getpass("Hugging Face token (input hidden): ").strip() if args.prompt_token else os.environ.get("HF_TOKEN")
    repos = {"small": "mlx-community/whisper-small-mlx", "large-v3-turbo": "mlx-community/whisper-large-v3-turbo"}
    requested = {} if args.diarization_only else {args.asr: repos[args.asr]}
    if args.diarization or args.diarization_only:
        if not token:
            parser.error("Configure HF_TOKEN or use --prompt-token after accepting Community-1 access terms")
        requested["diarization"] = "pyannote/speaker-diarization-community-1"
    from huggingface_hub import snapshot_download

    data_dir = Path(os.environ.get("STT_DATA_DIR", str(ROOT / ".runtime"))).expanduser()
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    directory = data_dir.resolve() / "models"
    directory.mkdir(parents=True, exist_ok=True)
    manifest_file = directory / "manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else {}
    for key, repo in requested.items():
        # A container's writable layer is transient; snapshots belong beside the
        # manifest in STT_DATA_DIR so native backups and Docker volumes keep both.
        path = snapshot_download(repo, token=token, cache_dir=str(directory / "hub"))
        manifest[key] = {"repo": repo, "path": path, "revision": Path(path).name}
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"Prepared {key}, revision {Path(path).name}")


if __name__ == "__main__":
    main()
