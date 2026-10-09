"""Etiquetado mínimo de hablantes: ids de Deepgram -> speaker_1, speaker_2... por orden de aparición.

Las reglas completas (estabilización, anti-eco, vocabulario) son del change `diarized-transcript`.
"""
from __future__ import annotations

from collections import defaultdict

from app.voice.deepgram import Word


class SpeakerMap:
    def __init__(self) -> None:
        self._map: dict[int, str] = {}

    def label(self, dg_id: int | None) -> str:
        if dg_id is None:
            return "user"
        if dg_id not in self._map:
            self._map[dg_id] = f"speaker_{len(self._map) + 1}"
        return self._map[dg_id]

    def majority(self, words: list[Word]) -> str:
        """Hablante con más tiempo de habla en los palabras dadas."""
        dur: dict[int | None, int] = defaultdict(int)
        for w in words:
            dur[w.speaker] += max(1, w.end_ms - w.start_ms)
        if not dur:
            return "user"
        return self.label(max(dur, key=lambda k: dur[k]))


def split_runs(words: list[Word]) -> list[list[Word]]:
    """Agrupa palabras consecutivas del mismo hablante."""
    runs: list[list[Word]] = []
    for w in words:
        if runs and runs[-1][-1].speaker == w.speaker:
            runs[-1].append(w)
        else:
            runs.append([w])
    return runs
