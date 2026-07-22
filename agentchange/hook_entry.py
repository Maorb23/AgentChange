"""CLI entry point shared by installed hooks and fixture diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentchange-hook")
    subparsers = parser.add_subparsers(dest="action", required=True)
    capture = subparsers.add_parser("capture")
    capture.add_argument("--fixture", type=Path)
    capture.add_argument("--plugin-data", type=Path)
    capture.add_argument("--plugin-root", type=Path)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--fixture", type=Path)
    finalize.add_argument("--plugin-data", type=Path)
    finalize.add_argument("--plugin-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.plugin_root and not (args.plugin_root / ".codex-plugin" / "plugin.json").is_file():
        print("AgentChange hook received an invalid PLUGIN_ROOT", file=sys.stderr)
        return 1
    if args.plugin_root:
        import agentchange as agentchange_package

        source_package = str((args.plugin_root / "agentchange").resolve())
        if source_package not in agentchange_package.__path__:
            agentchange_package.__path__.insert(0, source_package)
    from agentchange.raw_capture import CaptureError, capture_payload
    try:
        raw = args.fixture.read_text(encoding="utf-8") if args.fixture else sys.stdin.read()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise CaptureError("hook payload must be a JSON object")
        plugin_data = args.plugin_data or os.environ.get("PLUGIN_DATA")
        if not plugin_data:
            raise CaptureError("PLUGIN_DATA is not set; diagnostic use requires --plugin-data")
        envelope = capture_payload(payload, plugin_data)
    except (OSError, json.JSONDecodeError, CaptureError) as exc:
        print(f"AgentChange capture failed: {exc}", file=sys.stderr)
        return 1
    if payload.get("hook_event_name") in {"UserPromptSubmit", "PreToolUse"}:
        turn_id = payload.get("turn_id")
        cwd = payload.get("cwd")
        if isinstance(turn_id, str) and turn_id and isinstance(cwd, str) and cwd:
            try:
                from agentchange.git_analysis import ensure_git_baseline

                ensure_git_baseline(Path(plugin_data), envelope["session_id"], turn_id, cwd)
            except Exception as exc:
                print(f"AgentChange baseline capture failed after raw capture: {exc}", file=sys.stderr)

    if args.action == "finalize":
        session_id = payload.get("session_id")
        turn_id = payload.get("turn_id")
        if payload.get("stop_hook_active") is True:
            print("{}")
            return 0
        try:
            from agentchange.finalizer import claim_ui_continuation, finalize_turn, load_finalized_receipt
            from agentchange.git_analysis import turn_directory
            from agentchange.receipt import render_ui_continuation_reason
            from agentchange.slack import ensure_delivery
            from agentchange.ui import settings as ui_settings, should_display

            existing = load_finalized_receipt(Path(plugin_data), session_id, turn_id)
            receipt = finalize_turn(Path(plugin_data), payload)
            if existing is not None:
                ensure_delivery(
                    Path(plugin_data),
                    turn_directory(Path(plugin_data), session_id, turn_id),
                    receipt,
                )
        except Exception as exc:
            print(f"AgentChange finalization failed after raw Stop capture: {exc}", file=sys.stderr)
            print("{}")
            return 0
        ui_configuration = ui_settings()
        if should_display(receipt, ui_configuration) and claim_ui_continuation(Path(plugin_data), session_id, turn_id):
            print(
                json.dumps(
                    {
                        "decision": "block",
                        "reason": render_ui_continuation_reason(receipt, mode=ui_configuration.mode),
                    }
                )
            )
        else:
            print("{}")
    elif args.fixture:
        try:
            from agentchange.normalize import normalize_envelope

            print(normalize_envelope(envelope).model_dump_json())
        except Exception as exc:
            from agentchange.raw_capture import record_normalization_error

            record_normalization_error(plugin_data, envelope["session_id"], envelope["event_id"], exc)
            print(f"AgentChange normalization failed after raw capture: {exc}", file=sys.stderr)
            return 1
    else:
        print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
