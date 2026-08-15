from album_dvd_burner.database import burn_code_pattern, parse_burn_number


def test_burn_code_pattern_uses_prefix():
    pattern = burn_code_pattern("R.P. No.")
    assert pattern.startswith("^")
    assert "No\\." in pattern
    assert pattern.endswith(" - RE$")


def test_parse_burn_number():
    assert parse_burn_number("R.P. No. 007 - RE") == 7
    assert parse_burn_number("Custom 001 - RE") == 1
    assert parse_burn_number("invalid") is None
