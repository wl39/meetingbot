from collections import Counter, defaultdict

from .engines.base import Turn


def overlap(a, b):
    return max(0.0, min(a.end, b.end) - max(a.start, b.start))


def exclusive(turns):
    changes = defaultdict(Counter)
    for turn in turns:
        changes[turn.start][turn.speaker] += 1
        changes[turn.end][turn.speaker] -= 1
    points = sorted(changes)
    active = Counter()
    result = []
    for a, b in zip(points, points[1:]):
        active.update(changes[a])
        labels = {speaker for speaker, count in active.items() if count > 0}
        if len(labels) == 1:
            result.append(Turn(a, b, next(iter(labels))))
    return result


class SpeakerMapper:
    def __init__(self):
        self.previous = []
        self.next_id = 1

    def map(self, turns):
        current = exclusive(turns)
        labels = sorted({t.speaker for t in current})
        old_labels = sorted({t.speaker for t in self.previous})
        scores = {
            (new, old): sum(
                overlap(a, b) for a in current for b in self.previous if a.speaker == new and b.speaker == old
            )
            for new in labels
            for old in old_labels
        }
        mapping = {}
        for new in labels:
            ranked = sorted(((scores[new, old], old) for old in old_labels), reverse=True)
            if ranked and ranked[0][0] >= 0.35:
                score, old = ranked[0]
                total_new = sum(scores[new, o] for o in old_labels)
                total_old = sum(scores[n, old] for n in labels)
                # Split/merge ambiguity is intentionally unresolved.
                if score / max(total_new, 0.001) >= 0.7 and score / max(total_old, 0.001) >= 0.7:
                    mapping[new] = old
            elif sum(t.end - t.start for t in current if t.speaker == new) >= 0.35:
                # A new ID is only justified by speech outside the previously analysed time range.
                previous_end = max((t.end for t in self.previous), default=0)
                novel = sum(max(0, t.end - max(t.start, previous_end)) for t in current if t.speaker == new)
                if novel >= 0.35:
                    mapping[new] = f"spk_{self.next_id:02d}"
                    self.next_id += 1
        mapped = [Turn(t.start, t.end, mapping[t.speaker]) for t in turns if t.speaker in mapping]
        # Keep prior evidence for ambiguous labels instead of erasing identity history.
        if mapping:
            covered = [(t.start, t.end) for t in exclusive(mapped)]
            self.previous = exclusive(mapped) + [
                t for t in self.previous if not any(a < t.end and b > t.start for a, b in covered)
            ]
        return mapped
