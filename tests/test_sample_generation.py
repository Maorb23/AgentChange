import json

from scripts.generate_demo_events import generate


def test_fixture_based_sample_generation(tmp_path):
    output = tmp_path / "sample.jsonl"
    events = generate(tmp_path / "plugin-data", output)
    serialized = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(events) == len(serialized) == 11
    assert any(event["command"] == "agentchange-run -- ruff check ." and event["result_status"] == "succeeded" for event in serialized)
    assert any(event["command"] == "agentchange-run -- pytest -q" and event["result_status"] == "failed" for event in serialized)
    stop = serialized[-1]
    assert stop["event_type"] == "turn_stopped"
    assert stop["evidence_confidence"] == "reported"
