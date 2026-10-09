"""Arma enunciados completos a partir de los resultados de Deepgram.

Deepgram entrega trozos: parciales que cambian y finales (`is_final`) que fijan un tramo de audio.
Mostrar cada final como un enunciado aparte parte las frases en pedazos. Aquí los finales de un mismo
hablante se acumulan en un único `utt_id`, que se emite como `transcript.partial` (texto acumulado más el
tramo provisional) hasta el fin del enunciado (`speech_final` / `UtteranceEnd`) o un cambio de hablante,
y entonces sale un solo `transcript.final` con el texto completo.

Estabilización mínima: el hablante de un enunciado se fija con su primer tramo y una racha de otro
hablante más corta que `MIN_RUN_MS` no lo cambia (reglas completas en `diarized-transcript`).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.voice.deepgram import Segment, Word
from app.voice.speakers import SpeakerMap, split_runs
from app.ws import protocol as P
from app.ws.session import SessionContext

MIN_RUN_MS = 500


@dataclass
class _Utt:
    utt_id: str
    speaker: str
    ts: int
    ts_end: int
    text: str = ""


def merge_short_runs(runs: list[list[Word]], min_ms: int = MIN_RUN_MS) -> list[list[Word]]:
    """Une al vecino las rachas de otro hablante demasiado cortas para ser un cambio real."""
    out: list[list[Word]] = []
    for run in runs:
        dur = run[-1].end_ms - run[0].start_ms
        if out and dur < min_ms:
            out[-1] = out[-1] + [Word(w.text, w.start_ms, w.end_ms, out[-1][0].speaker) for w in run]
        elif out and out[-1][0].speaker == run[0].speaker:
            out[-1] = out[-1] + run
        else:
            out.append(run)
    if len(out) > 1 and out[0][-1].end_ms - out[0][0].start_ms < min_ms:   # racha inicial corta
        out[1] = [Word(w.text, w.start_ms, w.end_ms, out[1][0].speaker) for w in out[0]] + out[1]
        out = out[1:]
    return out


def _join(a: str, b: str) -> str:
    return f"{a} {b}".strip() if a else b.strip()


class UtteranceAssembler:
    def __init__(self, ctx: SessionContext, speakers: SpeakerMap) -> None:
        self.ctx = ctx
        self.speakers = speakers
        self.cur: _Utt | None = None

    async def on_segment(self, seg: Segment, turn_id: str) -> list[str]:
        """Procesa un resultado con texto. Devuelve los textos de los enunciados que quedaron cerrados."""
        ctx, closed = self.ctx, []
        if not seg.is_final:
            if self.cur is None:
                ts = seg.words[0].start_ms if seg.words else ctx.ts_ms
                self.cur = _Utt(ctx.ids.next_utt(), self.speakers.majority(seg.words), ts, ts)
            await self._partial(turn_id, _join(self.cur.text, seg.transcript))
            return closed
        runs = merge_short_runs(split_runs(seg.words)) if seg.words else []
        pieces = [(" ".join(w.text for w in r) if len(runs) > 1 else seg.transcript, r) for r in runs] \
            or [(seg.transcript, [])]
        for text, run in pieces:
            speaker = self.speakers.majority(run) if run else (self.cur.speaker if self.cur else "user")
            if self.cur is not None and self.cur.text and speaker != self.cur.speaker:
                closed += await self.flush(turn_id)
            if self.cur is None:
                ts = run[0].start_ms if run else ctx.ts_ms
                self.cur = _Utt(ctx.ids.next_utt(), speaker, ts, ts)
            elif not self.cur.text:
                self.cur.speaker = speaker               # el primer tramo confirmado fija el hablante
            self.cur.text = _join(self.cur.text, text)
            if run:
                self.cur.ts_end = max(self.cur.ts_end, run[-1].end_ms)
        await self._partial(turn_id, self.cur.text)
        return closed

    async def flush(self, turn_id: str) -> list[str]:
        """Fin del enunciado: emite el `transcript.final` con el texto completo."""
        cur, self.cur = self.cur, None
        if cur is None or not cur.text:
            return []
        await self.ctx.emit(P.TranscriptFinal, turn_id=turn_id, utt_id=cur.utt_id, speaker=cur.speaker, ts=cur.ts,
                            ts_end=max(cur.ts, cur.ts_end), text=cur.text, source="deepgram", degraded=False)
        return [cur.text]

    async def _partial(self, turn_id: str, text: str) -> None:
        cur = self.cur
        await self.ctx.emit(P.TranscriptPartial, turn_id=turn_id, utt_id=cur.utt_id, speaker=cur.speaker,
                            ts=cur.ts, text=text, source="deepgram", degraded=False)
