from catalog.ingest.bcsd.vtt import parse_vtt

# Mirrors the real BCSD format: real cue (carryover + tagged new line),
# then a 10ms preview cue restating the new line as plain text.
ROLLING = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000 align:start position:0%
 
good<00:00:00.500><c> afternoon</c>

00:00:02.000 --> 00:00:02.010 align:start position:0%
good afternoon


00:00:02.000 --> 00:00:04.000 align:start position:0%
good afternoon
the<00:00:02.500><c> board</c><00:00:03.000><c> will</c><00:00:03.500><c> come</c>

00:00:04.000 --> 00:00:04.010 align:start position:0%
the board will come


00:00:04.000 --> 00:00:06.000 align:start position:0%
the board will come
[Music]
"""


def test_dedup_emits_each_phrase_once():
    segs = parse_vtt(ROLLING)
    texts = [s.text for s in segs]
    assert texts == ["good afternoon", "the board will come"]


def test_inline_tags_are_stripped():
    segs = parse_vtt(ROLLING)
    assert all("<" not in s.text and "</c>" not in s.text for s in segs)


def test_music_noise_is_dropped():
    segs = parse_vtt(ROLLING)
    assert all("[Music]" not in s.text for s in segs)


def test_starts_are_monotonic_and_nonoverlapping():
    segs = parse_vtt(ROLLING)
    assert segs[0].start == 0.0
    assert segs[1].start == 2.0
    # each segment's end is clamped to the next segment's start
    assert segs[0].end == segs[1].start
    for a, b in zip(segs, segs[1:], strict=False):
        assert a.start < b.start
        assert a.end <= b.start


def test_empty_input_returns_empty_tuple():
    assert parse_vtt("WEBVTT\n\n") == ()


def test_seconds_conversion_handles_hours():
    vtt = "WEBVTT\n\n01:02:03.500 --> 01:02:05.000 align:start position:0%\nhello world\n"
    segs = parse_vtt(vtt)
    assert segs[0].start == 3723.5  # 1h2m3.5s


# A within-cue line that is only whitespace (a single space) is YouTube's
# carryover/typing placeholder, NOT a cue boundary. Only a truly-empty line
# separates cues in WebVTT. If _cues() split on whitespace-only lines, the
# real content line after the placeholder would be orphaned and lost. This
# fixture puts a space-placeholder line ahead of each real content line.
WHITESPACE_PLACEHOLDER = """WEBVTT

00:00:00.000 --> 00:00:02.000 align:start position:0%
 
good afternoon

00:00:02.000 --> 00:00:04.000 align:start position:0%
 
the board will come
"""


def test_within_cue_whitespace_line_does_not_split_cue():
    segs = parse_vtt(WHITESPACE_PLACEHOLDER)
    assert [s.text for s in segs] == ["good afternoon", "the board will come"]
