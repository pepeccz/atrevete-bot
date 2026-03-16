import pytest

from agent.graphs.conversation_flow import _extract_suggested_name


@pytest.mark.parametrize(
    ("display_name", "expected"),
    [
        ("Sii Ofreceis", None),
        ("Ana Martinez", None),
        ("Carlos Garcia", "Carlos"),
        ("JoseManuel", "Josemanuel"),
        ("12345", None),
        ("Cliente", None),
        ("", None),
        (None, None),
    ],
)
def test_extract_suggested_name_confidence_threshold(display_name: str | None, expected: str | None):
    assert _extract_suggested_name(display_name) == expected
