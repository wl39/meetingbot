import os

from .base import DiarizationResult, Turn


def select_device(torch, requested="auto"):
    if requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def bounded_training_set(embeddings, chunk_indices, speaker_indices, limit=4096):
    """Spread clustering training samples over the entire recording.

    Assignment still uses every embedding. Bounding AHC's quadratic distance
    matrix prevents hours of audio from exhausting the host's memory.
    """
    import numpy as np

    if len(embeddings) <= limit:
        return embeddings, chunk_indices, speaker_indices
    indices = np.linspace(0, len(embeddings) - 1, limit, dtype=int)
    return embeddings[indices], chunk_indices[indices], speaker_indices[indices]


class PyannoteEngine:
    def __init__(self, path, device="auto", cpu_threads=0, batch_size=8):
        import torch
        from pyannote.audio import Pipeline
        from pyannote.audio.pipelines.clustering import VBxClustering

        class BoundedVBxClustering(VBxClustering):
            def filter_embeddings(self, *args, **kwargs):
                return bounded_training_set(*super().filter_embeddings(*args, **kwargs))

        self.cpu_threads = cpu_threads or min(8, max(1, (os.cpu_count() or 2) // 2))
        torch.set_num_threads(self.cpu_threads)
        self.pipeline = Pipeline.from_pretrained(path)
        original = self.pipeline.clustering
        if isinstance(original, VBxClustering):
            bounded = BoundedVBxClustering(
                original.plda,
                metric=original.metric,
                constrained_assignment=original.constrained_assignment,
            )
            bounded.instantiate(original.parameters(instantiated=True))
            self.pipeline.clustering = bounded
        self.device = select_device(torch, device)
        self.pipeline.to(torch.device(self.device))
        self.pipeline.embedding_batch_size = batch_size
        self.pipeline.segmentation_batch_size = batch_size

    def diarize(self, audio, options, progress=None):
        import torch

        count = options.get("num_speakers")
        kwargs = {"num_speakers": count} if count else {"min_speakers": 1, "max_speakers": 8}
        from ..progress import DiarizationProgress

        reporter = DiarizationProgress(progress, self.device)
        reporter.start()
        try:
            output = self.pipeline(
                {"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": 16000},
                hook=reporter.hook, **kwargs,
            )
        except (RuntimeError, NotImplementedError) as exc:
            # Retry once for accelerator-specific failures; unrelated errors remain visible.
            if self.device == "cpu" or not any(
                marker in str(exc).lower() for marker in ("mps", "cuda", "out of memory", "not implemented")
            ):
                raise
            self.device = "cpu"
            self.pipeline.to(torch.device("cpu"))
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
            reporter = DiarizationProgress(progress, "cpu", fallback=True)
            reporter.start()
            output = self.pipeline(
                {"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": 16000},
                hook=reporter.hook, **kwargs,
            )
        annotation = output.speaker_diarization
        turns = [Turn(t.start, t.end, label) for t, _, label in annotation.itertracks(yield_label=True)]
        overlaps = []
        turns.sort(key=lambda t: t.start)
        for i, a in enumerate(turns):
            for j in range(i + 1, len(turns)):
                b = turns[j]
                if b.start >= a.end:
                    break
                lo, hi = max(a.start, b.start), min(a.end, b.end)
                if a.speaker != b.speaker and hi > lo:
                    overlaps.append((lo, hi))
        reporter.finish()
        return DiarizationResult(turns, overlaps, {
            "device": self.device, "cpu_threads": self.cpu_threads,
            "max_clustering_training_embeddings": 4096,
        })
