import pytest

from prestige.guard.labels import ALL, LATEST, VERSIONS, LabelError, Labels, ToolLabel


def write(tmp_path, name, text):
    path = tmp_path / f"{name}.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_bundled_labels_load_and_merge():
    labels = Labels.load("banking", "slack")
    assert labels.get("send_money") == ToolLabel("boundary", ("recipient",))
    assert labels.get("get_channels").trusted_output
    assert labels.get("not_a_tool") == ToolLabel("state", ALL)


def test_conflicting_labels_are_rejected(tmp_path):
    a = write(tmp_path, "a", "tools:\n  t: {impact: read}\n")
    b = write(tmp_path, "b", "tools:\n  t: {impact: state, sinks: [x]}\n")
    with pytest.raises(LabelError, match="labelled differently"):
        Labels.load(a, b)


@pytest.mark.parametrize(
    "text",
    [
        "tools:\n  t: {impact: delete}\n",
        "tools:\n  t: {impact: read, sinks: [x]}\n",
        "tools:\n  t: {impact: state, sinks: x}\n",
        "tools:\n  t: {impact: state, extra: 1}\n",
        "other: 1\n",
    ],
)
def test_bad_labels_are_rejected(tmp_path, text):
    with pytest.raises(LabelError):
        Labels.load(write(tmp_path, "bad", text))


def test_unknown_names_are_rejected():
    with pytest.raises(LabelError, match="no bundled one"):
        Labels.load("no_such_suite")
    with pytest.raises(LabelError, match="unknown label version"):
        Labels.load("banking@v9")


def test_versions_load_by_suffix_and_latest_is_default():
    assert Labels.load("banking") == Labels.load(f"banking@{LATEST}")
    assert Labels.load("banking@v1").get("send_money") == ToolLabel("boundary", ("recipient",))


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("suite", ["banking", "slack"])
def test_bundled_labels_match_agentdojo_tools(suite, version):
    load_suites = pytest.importorskip("agentdojo.task_suite.load_suites")
    tools = {t.name: set(t.parameters.model_json_schema().get("properties", {})) for t in load_suites.get_suite("v1.2.2", suite).tools}
    labels = Labels.load(f"{suite}@{version}")
    assert set(labels.tools) == set(tools)
    for name, label in labels.tools.items():
        assert label.sinks == ALL or set(label.sinks) <= tools[name], name
