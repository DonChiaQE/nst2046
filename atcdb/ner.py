"""Parse ATCO2-style inline markup into plain text plus word-index spans.

Markup seen in the ATCO2 XML (real data is inconsistent in case and spacing):
  [#callsign]Swiss[/#callsign]      NER tags (callsign / command / value / unnamed / nonenglish), one per word
  [NE-French]bonne soiree[/NE]      language markers ([NE Slovak], [Ne Czech], [NE], closed by [/NE], [/Ne], [\\NE]);
                                    they may open and close inside NER tags
  [hes] [noise] [spk] [XT] [ukn]    event markers: hesitation, noise, speaker change, crosstalk, unintelligible

Output: (lowercased text, spans). Event markers are kept as bracketed tokens ("[hes]") so a
downstream normaliser can drop them trivially; each also gets a single-word span. Language
markers vanish from the text and become "nonenglish" spans. Spans are (start, end, category),
end inclusive; at equal start, NER spans sort before "nonenglish".
"""
import re

_TOKEN_RE = re.compile(r"\[(?P<tag>[^\]]*)\]|(?P<word>[^\s\[\]]+)")
_LANG_OPEN_RE = re.compile(r"^ne(?:[-_ ]\w+)?$", re.I)
_LANG_CLOSE_RE = re.compile(r"^[/\\]ne$", re.I)
MARKER_CATEGORIES = {"hes": "hesitation", "noise": "noise", "spk": "speaker_change", "xt": "crosstalk", "ukn": "unintelligible"}


def _extend(spans: list, idx: int, cat: str, force_new: bool = False) -> None:
    if not force_new and spans and spans[-1][2] == cat and spans[-1][1] == idx - 1:
        spans[-1] = (spans[-1][0], idx, cat)
    else:
        spans.append((idx, idx, cat))


def parse_ner_text(tagged: str) -> tuple[str, list[tuple[int, int, str]]]:
    words: list[str] = []
    ner_spans: list[tuple[int, int, str]] = []
    other_spans: list[tuple[int, int, str]] = []
    cat = None
    in_lang = False
    lang_region_started = False  # True until the first word after a language-open marker

    def add_word(w: str) -> int:
        nonlocal lang_region_started
        idx = len(words)
        words.append(w)
        if cat:
            _extend(ner_spans, idx, cat)
        if in_lang:
            _extend(other_spans, idx, "nonenglish", force_new=lang_region_started)
            lang_region_started = False
        return idx

    for m in _TOKEN_RE.finditer(tagged or ""):
        if m.group("word") is not None:
            add_word(m.group("word").lower())
            continue
        tag = m.group("tag").strip()
        if tag.startswith("#"):
            cat = tag[1:].strip().lower()
        elif tag.startswith("/#"):
            cat = None
        elif _LANG_OPEN_RE.match(tag):
            in_lang = True
            lang_region_started = True
        elif _LANG_CLOSE_RE.match(tag):
            in_lang = False
        else:
            name = tag.lower()
            idx = add_word(f"[{name}]")
            _extend(other_spans, idx, MARKER_CATEGORIES.get(name, name))
    spans = sorted(ner_spans + other_spans, key=lambda s: (s[0], s[2] == "nonenglish"))
    return " ".join(words), spans
