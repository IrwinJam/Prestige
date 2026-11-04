import pytest

pytest.importorskip("agentdojo")

from prestige.eval import demo  # noqa: E402


def test_demo_shows_the_block_and_no_tool_output(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert demo.main([]) == 0
    out = capsys.readouterr().out
    assert "guard off\n  attack worked" in out
    assert "blocked send_money.recipient: the value came only from read_file\n  attack failed" in out
    assert len(out.splitlines()) < 12
