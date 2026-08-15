#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import tempfile
from pathlib import Path

from translation_quality import correct_translation_srt, parse_srt


SOURCE = """1
00:00:00,000 --> 00:00:02,000
That was my only chance. At least if something happened

2
00:00:02,010 --> 00:00:04,000
to me, at least if I died trying.

3
00:00:04,010 --> 00:00:06,000
That was so free.

4
00:00:06,010 --> 00:00:08,000
♪ music ♪
"""

RAW = """1
00:00:00,000 --> 00:00:02,000
Das war meine einzige Chance. Zumindest wenn etwas passiert ist

2
00:00:02,010 --> 00:00:04,000
für mich, zumindest wenn ich bei dem Versuch gestorben wäre.

3
00:00:04,010 --> 00:00:06,000
Das war so kostenlos.

4
00:00:06,010 --> 00:00:08,000
♪ Musik ♪
"""


def fake_request(**kwargs):
    schema = kwargs["schema"]
    ids = sorted(
        {
            value
            for value in schema["properties"]["corrections"]["items"]["properties"]["id"]["enum"]
        }
    )
    mapping = {
        1: "Das war meine einzige Chance. Selbst wenn mir etwas zugestoßen wäre –",
        2: "selbst wenn ich bei dem Versuch gestorben wäre.",
        3: "Das fühlte sich so frei an.",
    }
    return json.dumps(
        {
            "corrections": [
                {"id": idx, "text": mapping[idx]}
                for idx in ids
            ]
        },
        ensure_ascii=False,
    )


def main():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / "source.srt"
        raw = root / "raw.srt"
        output = root / "corrected.srt"
        source.write_text(SOURCE, encoding="utf-8")
        raw.write_text(RAW, encoding="utf-8")

        result = correct_translation_srt(
            source,
            raw,
            output,
            model="test-model",
            batch_size=10,
            request_fn=fake_request,
        )
        cues = parse_srt(output)

        assert "Selbst wenn mir" in cues[0].text
        assert cues[1].text.startswith("selbst wenn")
        assert cues[2].text == "Das fühlte sich so frei an."
        assert cues[3].text == "♪ Musik ♪"
        assert result.changed_blocks == 3
        print("OK: Satzübergreifende Korrektur, Strukturerhalt und Musikschutz funktionieren.")


if __name__ == "__main__":
    main()
