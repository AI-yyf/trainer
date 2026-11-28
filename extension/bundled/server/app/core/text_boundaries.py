"""Where a clause ends in learner-written text.

An ASCII ``.``, ``!`` or ``?`` ends a clause only at the edge of a word: inside a word it belongs
to a name — ``refunds.py``, ``v3.11``, ``example.com``. A first clause split at that dot stored the
focus "我在 refunds" and titled a task "Add retries to payments" (seen with a real model on
2026-11-28).
"""

from __future__ import annotations

import re

_ASCII_END_AT_A_WORD_EDGE = r"[.!?](?!\w)|(?<!\w)[.!?]"

#: Commas end a clause too: what precedes them is the clause.
CLAUSE_END_PATTERN = re.compile(f"[，。！？；,\\n]|{_ASCII_END_AT_A_WORD_EDGE}")

#: Only full stops end a sentence.
SENTENCE_END_PATTERN = re.compile(f"[。！？\\n]|{_ASCII_END_AT_A_WORD_EDGE}")
