from .base import ASRResult, Word


class FasterWhisperEngine:
    def __init__(self, path):
        from faster_whisper import WhisperModel

        self.model = WhisperModel(path, device="cpu", compute_type="int8", local_files_only=True)

    def transcribe(self, audio, options):
        segments, info = self.model.transcribe(
            audio, language=options["language"], word_timestamps=True,
            condition_on_previous_text=False, vad_filter=False,
        )
        words = []
        for segment in segments:
            if segment.text.strip() and not segment.words:
                raise RuntimeError("ASR returned text without word timestamps")
            words.extend(Word(w.start, w.end, w.word) for w in (segment.words or []))
        return ASRResult(words, info.language, {"timestamp_source": "whisper_attention", "runtime": "cpu-int8"})
