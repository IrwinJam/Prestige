import json

import pytest

pytest.importorskip("agentdojo")

from prestige.eval.agentdojo import build_pipeline, suite  # noqa: E402
from prestige.eval.published import PublishedAttack, make  # noqa: E402

STAND_IN = 'A neutral "quoted" line.\n\nA second line: with a colon.'


def test_published_text_lands_in_the_environment_exactly(tmp_path):
    s = suite("banking")
    path = tmp_path / "injections.json"
    cells = {i: {v: {"variants": [STAND_IN], "original": "other"} for v in s.get_injection_vector_defaults()} for i in s.injection_tasks}
    path.write_text(json.dumps({"suite": "banking", "injection_tasks": cells}), encoding="utf-8")
    pipeline = build_pipeline("http://127.0.0.1:1/v1", "muse-spark-1.3")
    attack = make(f"autodojo:{path}", s, pipeline)
    assert isinstance(attack, PublishedAttack)
    injections = attack.attack(s.get_user_task_by_id("user_task_0"), s.get_injection_task_by_id("injection_task_0"))
    env = s.load_and_inject_default_environment(injections)
    assert json.dumps(STAND_IN)[1:-1] in json.dumps(env.model_dump(mode="json"))


def test_wrong_suite_is_refused(tmp_path):
    path = tmp_path / "injections.json"
    path.write_text(json.dumps({"suite": "slack", "injection_tasks": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        PublishedAttack(suite("banking"), build_pipeline("http://127.0.0.1:1/v1", "m"), path)


def test_other_names_go_to_agentdojo():
    assert make("important_instructions", None, None) is None
