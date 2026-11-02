import os

from prestige.__main__ import load_env


def test_load_env_reads_values_and_keeps_what_is_set(tmp_path, monkeypatch):
    monkeypatch.delenv("PRESTIGE_TEST_NEW", raising=False)
    monkeypatch.setenv("PRESTIGE_TEST_SET", "from-shell")
    path = tmp_path / ".env"
    path.write_text('# note\nPRESTIGE_TEST_NEW="abc"\nPRESTIGE_TEST_SET=from-file\nnot a pair\n', encoding="utf-8")
    load_env(path)
    assert os.environ["PRESTIGE_TEST_NEW"] == "abc"
    assert os.environ["PRESTIGE_TEST_SET"] == "from-shell"
    monkeypatch.delenv("PRESTIGE_TEST_NEW")


def test_load_env_without_a_file_does_nothing(tmp_path):
    load_env(tmp_path / "missing")
