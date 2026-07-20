"""CLI entry point shared by installed hooks and fixture diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__:
    from .raw_capture import CaptureError, capture_payload
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from agentchange.raw_capture import CaptureError, capture_payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentchange-hook")
    subparsers = parser.add_subparsers(dest="action", required=True)
    capture = subparsers.add_parser("capture")
    capture.add_argument("--fixture", type=Path)
    capture.add_argument("--plugin-data", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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
    if args.fixture:
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
