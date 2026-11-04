import sys

import pytest

from dopplergeist.cli import main


@pytest.mark.parametrize(
    ("option", "value", "message"),
    [
        ("--max-upload-mb", "0", "Value must be a positive integer"),
        ("--max-upload-mb", "-1", "Value must be a positive integer"),
        ("--port", "-1", "Port must be between 0 and 65535"),
        ("--port", "65536", "Port must be between 0 and 65535"),
    ],
)
def test_serve_rejects_invalid_limits_before_startup(monkeypatch, capsys, tmp_path, option, value, message):
    jobs = tmp_path / "jobs"
    monkeypatch.setattr(sys, "argv", ["dopplergeist", "serve", "--jobs", str(jobs), option, value])

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
    assert message in capsys.readouterr().err
    assert not jobs.exists()
