"""Example meeting controller consumer. No RAG or speech-engine dependencies."""

from .utterance import UtteranceEvent


class TranscriptConsumer:
    def __init__(self):
        self.seen = set()
        self.latest = {}

    def accept(self, event: UtteranceEvent) -> bool:
        if event.event_id in self.seen:
            return False
        self.seen.add(event.event_id)
        if event.status == "partial":
            return False
        key = (event.session_id, event.utterance_id)
        previous = self.latest.get(key)
        if previous and previous.revision >= event.revision:
            return False
        self.latest[key] = event
        return True
