"""Create a controlled failed-test/positive-claim contradiction receipt."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from agentchange.finalizer import finalize_turn
from agentchange.git_analysis import ensure_git_baseline, turn_directory
from agentchange.raw_capture import capture_payload
from agentchange.receipt import canonical_bytes, render_markdown

ROOT = Path(__file__).resolve().parents[1]


def _export_sanitized_examples(receipt: dict) -> None:
    sample = copy.deepcopy(receipt)
    for snapshot_name in ("baseline", "final"):
        snapshot = sample["repository"].get(snapshot_name)
        if snapshot and snapshot.get("repository_root"):
            snapshot["repository_root"] = "/workspace/agentchange-demo"
    body = {key: value for key, value in sample.items() if key != "integrity"}
    sample["integrity"]["canonical_receipt_body"]["digest"] = hashlib.sha256(canonical_bytes(body)).hexdigest()
    markdown_body = render_markdown(sample, include_integrity=False)
    sample["integrity"]["markdown_body"]["digest"] = hashlib.sha256(markdown_body.encode("utf-8")).hexdigest()
    (ROOT / "examples" / "sample_receipt.json").write_text(
        json.dumps(sample, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (ROOT / "examples" / "sample_receipt.md").write_text(render_markdown(sample, include_integrity=True), encoding="utf-8")


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(repo), *arguments], check=True, capture_output=True)


def _payload(repo: Path, event: str, **extra: object) -> dict:
    value = {
        "session_id": "agentchange-controlled-demo",
        "turn_id": "contradiction-turn",
        "cwd": str(repo),
        "hook_event_name": event,
        "model": "demo-model",
        "permission_mode": "default",
    }
    value.update(extra)
    return value


def run_demo(output: Path, export_examples: bool) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    repo = output / "repo"
    data = output / "plugin-data"
    repo.mkdir(exist_ok=False)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "demo@agentchange.invalid")
    _git(repo, "config", "user.name", "AgentChange Demo")
    (repo / "README.md").write_text("demo baseline\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "baseline")

    session_id, turn_id = "agentchange-controlled-demo", "contradiction-turn"
    capture_payload(_payload(repo, "UserPromptSubmit", prompt="Add a small authentication helper and test it."), data)
    ensure_git_baseline(data, session_id, turn_id, str(repo))
    (repo / "auth.py").write_text("def allowed():\n    return True\n", encoding="utf-8")
    capture_payload(
        _payload(repo, "PreToolUse", tool_name="apply_patch", tool_use_id="write-auth", tool_input={"command": "*** Begin Patch\n*** Add File: auth.py\n+def allowed(): return True\n*** End Patch"}),
        data,
    )
    command = "agentchange-run -- pytest -q"
    capture_payload(_payload(repo, "PreToolUse", tool_name="Bash", tool_use_id="tests", tool_input={"command": command}), data)
    capture_payload(
        _payload(
            repo,
            "PostToolUse",
            tool_name="Bash",
            tool_use_id="tests",
            tool_input={"command": command},
            tool_response="1 failed\n__AGENTCHANGE_RESULT__={\"schema_version\":\"1\",\"exit_code\":1,\"duration_ms\":29}",
        ),
        data,
    )
    stop = _payload(repo, "Stop", stop_hook_active=False, last_assistant_message="Implemented the authentication helper. All tests pass.")
    capture_payload(stop, data)
    receipt = finalize_turn(data, stop)
    receipt_dir = turn_directory(data, session_id, turn_id)
    if export_examples:
        _export_sanitized_examples(receipt)
    codes = {item["code"] for item in receipt["findings"]}
    if "TEST_CLAIM_CONTRADICTION" not in codes:
        raise RuntimeError("controlled demo did not produce the required contradiction")
    print(json.dumps({"receipt_id": receipt["receipt_id"], "risk": receipt["risk"], "findings": sorted(codes), "receipt_directory": str(receipt_dir)}, indent=2))
    return receipt_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--export-examples", action="store_true")
    args = parser.parse_args()
    if args.output:
        run_demo(args.output, args.export_examples)
    else:
        with tempfile.TemporaryDirectory(prefix="agentchange-phase2-demo-") as temporary:
            run_demo(Path(temporary), args.export_examples)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
