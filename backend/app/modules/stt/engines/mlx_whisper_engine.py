from .base import ASRResult, Word


class MLXWhisperEngine:
    def __init__(self, path):
        import mlx.core as mx
        from mlx_whisper.transcribe import ModelHolder

        self.path = path
        ModelHolder.get_model(path, mx.float16)

    def transcribe(self, audio, options):
        import mlx_whisper

        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=self.path,
            language=options["language"],
            word_timestamps=True,
            verbose=None,
            condition_on_previous_text=False,
        )
        words = [
            Word(w["start"], w["end"], w["word"]) for s in result["segments"] for w in s.get("words", [])
        ]
        if result.get("text", "").strip() and not words:
            raise RuntimeError("ASR returned text without word timestamps")
        return ASRResult(words, result["language"], {"timestamp_source": "whisper_attention"})
