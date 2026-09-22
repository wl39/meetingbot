"""Server-owned engine/model catalog; API callers never provide package names or URLs."""
import importlib.util
import json
import platform
from pathlib import Path

ENGINES = {
    "mlx": {"name": "MLX Whisper", "module": "mlx_whisper", "package": "mlx-whisper>=0.4,<0.5"},
    "faster-whisper": {
        "name": "Faster Whisper · CPU", "module": "faster_whisper", "package": "faster-whisper>=1.2,<2",
    },
}
MODELS = {
    "mlx:small": {"repo": "mlx-community/whisper-small-mlx", "download_gb": 0.5},
    "mlx:large-v3-turbo": {"repo": "mlx-community/whisper-large-v3-turbo", "download_gb": 1.7},
    "faster-whisper:small": {"repo": "Systran/faster-whisper-small", "download_gb": 0.5},
    "faster-whisper:large-v3-turbo": {
        "repo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "download_gb": 1.7,
    },
}


def supported(engine):
    if engine == "mlx":
        return platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"}
    if platform.system() == "Windows":
        return platform.machine().lower() in {"x86_64", "amd64"}
    return platform.system() in {"Darwin", "Linux"} and platform.machine().lower() in {
        "x86_64", "amd64", "arm64", "aarch64",
    }


def default_engine():
    return "mlx" if supported("mlx") else "faster-whisper"


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def python_in(directory):
    return directory / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")


def engine_python(data_dir, engine):
    directory = data_dir / "engines" / engine
    executable = python_in(directory)
    return executable if executable.is_file() and (directory / "installed.json").is_file() else None


def engine_installed(data_dir, engine):
    return bool(engine_python(data_dir, engine)) or importlib.util.find_spec(ENGINES[engine]["module"]) is not None


def installed_models(data_dir):
    manifest = read_json(data_dir / "models" / "manifest.json", {})
    result = {key: value for key, value in manifest.items() if key in MODELS}
    # Existing releases wrote bare model names for MLX. Keep their snapshots usable.
    for model in ("small", "large-v3-turbo"):
        if model in manifest:
            result.setdefault("mlx:" + model, manifest[model])
    return result


def model_installed(data_dir, engine, model):
    entry = installed_models(data_dir).get(engine + ":" + model, {})
    return bool(entry.get("path") and Path(entry["path"]).is_dir())


def worker_manifest(settings):
    engine = settings.asr_backend if settings.asr_backend != "auto" else default_engine()
    entries = installed_models(settings.data_dir)
    manifest = {}
    for model in ("small", "large-v3-turbo"):
        entry = entries.get(engine + ":" + model)
        if entry:
            manifest[model] = dict(entry, engine=engine)
            executable = engine_python(settings.data_dir, engine)
            if executable:
                manifest[model]["runtime_python"] = str(executable)
    legacy = read_json(settings.data_dir / "models" / "manifest.json", {})
    if "diarization" in legacy:
        manifest["diarization"] = legacy["diarization"]
    return manifest


def load_selection(settings):
    selection = read_json(settings.data_dir / "system-selection.json", {})
    if selection.get("engine") in ENGINES and selection.get("model") in {"small", "large-v3-turbo"}:
        settings.asr_backend = selection["engine"]
        settings.default_model = selection["model"]
