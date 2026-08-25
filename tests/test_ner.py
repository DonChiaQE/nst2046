from atcdb.ner import parse_ner_text

ATCO2_EXAMPLE = ("[#callsign]Bair[/#callsign] [#callsign]Nine[/#callsign] [#callsign]Five[/#callsign] "
                 "[#callsign]One [/#callsign] [#command]stand[/#command] [#command]by[/#command] "
                 "[#unnamed]call[/#unnamed] [#unnamed]you[/#unnamed] [#unnamed]back[/#unnamed]")


def test_strips_tags_and_lowercases_words():
    text, _ = parse_ner_text(ATCO2_EXAMPLE)
    assert text == "bair nine five one stand by call you back"


def test_merges_consecutive_same_category_words_into_spans():
    _, spans = parse_ner_text(ATCO2_EXAMPLE)
    assert spans == [(0, 3, "callsign"), (4, 5, "command"), (6, 8, "unnamed")]


def test_untagged_words_get_no_span():
    text, spans = parse_ner_text("[#callsign]Swiss[/#callsign] [#callsign]One[/#callsign] roger [#command]descend[/#command]")
    assert text == "swiss one roger descend"
    assert spans == [(0, 1, "callsign"), (3, 3, "command")]


def test_plain_text_without_tags():
    text, spans = parse_ner_text("Hotel Echo Lima affirm remain on my frequency")
    assert text == "hotel echo lima affirm remain on my frequency"
    assert spans == []


def test_empty_input():
    assert parse_ner_text("") == ("", [])


def test_hesitation_marker_becomes_a_token_with_a_span():
    text, spans = parse_ner_text("[hes] [#command]descend[/#command]")
    assert text == "[hes] descend"
    assert spans == [(0, 0, "hesitation"), (1, 1, "command")]


def test_other_markers_and_sloppy_variants():
    text, spans = parse_ner_text("[HES ] [noise] [spk] [XT] [ukn] [NE Slovak]dobry[\\NE] [Ne Czech]ahoj[/Ne] ok")
    assert text == "[hes] [noise] [spk] [xt] [ukn] dobry ahoj ok"
    assert spans == [(0, 0, "hesitation"), (1, 1, "noise"), (2, 2, "speaker_change"), (3, 3, "crosstalk"),
                     (4, 4, "unintelligible"), (5, 5, "nonenglish"), (6, 6, "nonenglish")]


def test_inline_language_markers_are_stripped_and_become_nonenglish_spans():
    # real ATCO2 form: language markers open/close INSIDE the per-word NER tags, mixed case
    text, spans = parse_ner_text("[hes] [#value][NE-French]le[/#value] [#value]Golf[/#value] [#value]de[/#value] "
                                 "[#value]Montana[/NE][/#value] [#value]three[/#value] [#value]thousand[/#value]")
    assert text == "[hes] le golf de montana three thousand"
    assert spans == [(0, 0, "hesitation"), (1, 6, "value"), (1, 4, "nonenglish")]


def test_language_marker_inside_ner_tag():
    text, spans = parse_ner_text("[#unnamed][ne-french]a[/#unnamed] [#unnamed]toute[/ne][/#unnamed] [#callsign]Swiss[/#callsign]")
    assert text == "a toute swiss"
    assert spans == [(0, 1, "unnamed"), (0, 1, "nonenglish"), (2, 2, "callsign")]
