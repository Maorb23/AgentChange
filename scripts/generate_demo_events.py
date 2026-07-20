"""Generate the Phase 1 sample from fixtures via production capture/normalization."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from agentchange.raw_capture import capture_payload
from agentchange.recorder import normalize_session

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "codex_hooks"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def generate(plugin_data: Path, output: Path) -> list:
    lint_pre = load("pre_tool_use_bash.json")
    lint_pre["tool_use_id"] = "tool-lint-001"
    lint_pre["tool_input"]["command"] = "python -m ruff check ."
    lint_post = load("post_tool_use_bash_success.json")
    lint_post["tool_use_id"] = "tool-lint-001"
    lint_post["tool_input"]["command"] = "python -m ruff check ."
    test_pre = load("pre_tool_use_bash.json")
    test_pre["turn_id"] = "turn-002"
    test_pre["tool_use_id"] = "tool-test-001"
    test_pre["tool_input"]["command"] = "python -m pytest -q"
    test_post = load("post_tool_use_bash_failed.json")
    test_post["tool_use_id"] = "tool-test-001"
    test_post["tool_input"]["command"] = "python -m pytest -q"
    test_post["tool_response"]["stderr"] = "1 failed, 12 passed"

    payloads = [
        load("session_start.json"),
        load("user_prompt_submit.json"),
        load("pre_tool_use_patch.json"),
        load("post_tool_use_patch.json"),
        load("pre_tool_use_dependency_patch.json"),
        lint_pre,
        lint_post,
        test_pre,
        test_post,
        load("permission_request.json"),
        load("stop.json"),
    ]
    for payload in payloads:
        capture_payload(payload, plugin_data)
    events = normalize_session(plugin_data, "demo-session-001")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(event.model_dump_json() + "\n" for event in events),
        encoding="utf-8",
    )
    return events


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-data", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "examples" / "sample_session.jsonl")
    args = parser.parse_args()
    if args.plugin_data:
        events = generate(args.plugin_data, args.output)
    else:
        with tempfile.TemporaryDirectory(prefix="agentchange-demo-") as temporary:
            events = generate(Path(temporary), args.output)
    print(f"Generated {len(events)} normalized events at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
