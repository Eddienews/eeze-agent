"""build_state must stay bounded — a restored Notepad tab can hold a whole document.

Found live (2026-09-23, GUI regression run): the session-restored Notepad fed an
unbounded element value into the Jev state and the provider answered
`max_tokens_exceeded` (HTTP 400, three attempts). The state rows sent to the brain
are now capped per value; the deterministic checks keep reading the RAW capture.
"""

from eeze_agent.core.loop import STATE_VALUE_CAP, build_state
from eeze_agent.core.models import Observation


def _obs(value: str | None) -> Observation:
    return Observation(
        pid=1,
        window_id=2,
        window_title="x - Notepad",
        elements=[
            {"element_index": 1, "role": "Document", "label": "Text editor", "value": value},
            {"element_index": 2, "role": "Button", "label": "Save", "value": None},
        ],
    )


def test_long_values_are_capped_with_an_explicit_marker():
    big = "A" * (STATE_VALUE_CAP + 500)
    rows = build_state(_obs(big), goal="g")["elements"]
    value = rows[0]["value"]
    assert value.startswith("A" * 100)
    assert value.endswith("[+500 more chars]")
    assert len(value) < STATE_VALUE_CAP + 60


def test_short_and_none_values_pass_through():
    rows = build_state(_obs("hello"), goal="g")["elements"]
    assert rows[0]["value"] == "hello"
    assert rows[1]["value"] is None
