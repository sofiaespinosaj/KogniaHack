"""Enunciados completos a partir de los tramos de Deepgram."""
from app.voice.deepgram import Segment, Word
from app.voice.speakers import SpeakerMap
from app.voice.transcript import UtteranceAssembler, merge_short_runs
from app.ws import protocol as P


class Ctx:
    def __init__(self):
        self.ids, self.events, self.ts_ms = P.TurnIds(), [], 0

    async def emit(self, cls, **f):
        self.events.append({"type": cls.model_fields["type"].default, **f})


def words(text, start, speaker, step=300):
    return [Word(w, start + i * step, start + (i + 1) * step, speaker) for i, w in enumerate(text.split())]


def seg(text, start, speaker, final=True, speech_final=False):
    return Segment(final, text, words(text, start, speaker), speech_final=speech_final)


async def test_pieces_become_one_complete_utterance():
    ctx = Ctx()
    asm = UtteranceAssembler(ctx, SpeakerMap())
    await asm.on_segment(seg("me accidenté", 0, 0, final=False), "t-0001")
    await asm.on_segment(seg("Me accidenté en Manizales,", 0, 0), "t-0001")
    await asm.on_segment(seg("a qué IPS", 1200, 0, final=False), "t-0001")
    await asm.on_segment(seg("¿a qué IPS puedo ir?", 1200, 0), "t-0001")
    closed = await asm.flush("t-0001")
    finals = [e for e in ctx.events if e["type"] == "transcript.final"]
    assert closed == ["Me accidenté en Manizales, ¿a qué IPS puedo ir?"]
    assert len(finals) == 1 and finals[0]["text"] == closed[0] and finals[0]["speaker"] == "speaker_1"
    assert {e["utt_id"] for e in ctx.events} == {"u-0001"}              # una sola burbuja
    partials = [e["text"] for e in ctx.events if e["type"] == "transcript.partial"]
    assert partials[2] == "Me accidenté en Manizales, a qué IPS"      # acumulado + tramo provisional
    assert finals[0]["ts"] == 0 and finals[0]["ts_end"] == 1200 + 5 * 300


async def test_speaker_change_closes_the_utterance():
    ctx = Ctx()
    asm = UtteranceAssembler(ctx, SpeakerMap())
    await asm.on_segment(seg("cuántas camas hay en Caldas", 0, 0), "t-0001")
    closed = await asm.on_segment(seg("y cuántas ambulancias", 2000, 1), "t-0001")
    closed += await asm.flush("t-0001")
    finals = [e for e in ctx.events if e["type"] == "transcript.final"]
    assert [f["speaker"] for f in finals] == ["speaker_1", "speaker_2"] and len(closed) == 2
    assert finals[0]["utt_id"] != finals[1]["utt_id"]


def test_short_runs_do_not_change_speaker():
    runs = [words("hola qué tal", 0, 0), words("eh", 900, 1, step=200), words("cuántas IPS hay", 1100, 0)]
    merged = merge_short_runs(runs)
    assert len(merged) == 1 and {w.speaker for w in merged[0]} == {0}
