"""Example tests for the `unit-convert` CLI: parsing, output, error exits."""

import pytest

from unit_converter import cli


def test_length_output(capsys):
    assert cli.main(["5", "km", "mi"]) == 0
    out = capsys.readouterr().out.strip()
    assert out == "5 km = 3.106855961 mi"


def test_temperature_output(capsys):
    assert cli.main(["72", "F", "C"]) == 0
    out = capsys.readouterr().out.strip()
    value = float(out.split("=")[1].split("°C")[0])
    assert value == pytest.approx(22.2222, abs=1e-4)
    assert "72 °F" in out


def test_currency_output_includes_snapshot_date(capsys):
    assert cli.main(["100", "USD", "EUR"]) == 0
    out = capsys.readouterr().out.strip()
    assert "100 USD = 92.0 EUR" in out
    assert "(static rates as of 2026-10-01)" in out


def test_currency_lowercase_input(capsys):
    assert cli.main(["1", "gbp", "usd"]) == 0
    out = capsys.readouterr().out.strip()
    assert "1 GBP = 1.265822785 USD" in out


def test_unknown_unit_one_line_error_exit_2(capsys):
    assert cli.main(["5", "km", "nonsense"]) == 2
    err = capsys.readouterr().err.strip()
    assert err == "error: unknown unit 'nonsense'"


def test_invalid_number_exit_2(capsys):
    assert cli.main(["abc", "km", "mi"]) == 2
    err = capsys.readouterr().err.strip()
    assert err == "error: invalid number 'abc'"


def test_missing_argument_one_line_error(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["5", "km"])
    assert excinfo.value.code == 2
    assert capsys.readouterr().err.count("\n") == 1


def test_mixed_categories_rejected(capsys):
    assert cli.main(["1", "km", "kg"]) == 2
    assert "error:" in capsys.readouterr().err
