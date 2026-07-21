import json
from pathlib import Path


REQUIRED_EVENTS = {
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "Stop",
}


def test_manifest_and_hook_configuration_are_valid():
    manifest = json.loads(Path(".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    hooks = json.loads(Path("hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
    assert manifest["name"] == "agentchange"
    assert "hooks" not in manifest
    assert set(hooks) == REQUIRED_EVENTS
    for groups in hooks.values():
        for group in groups:
            for handler in group["hooks"]:
                assert "${PLUGIN_ROOT}" in handler["command"]
                assert handler["timeout"] == 10

    project = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'agentchange-run = "agentchange.command_runner:main"' in project
    assert 'agentchange-hook = "agentchange.hook_entry:main"' in project


def test_skill_frontmatter_and_runtime_data_contract():
    skill = Path("skills/agentchange/SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: agentchange\n")
    assert "description:" in skill.split("---", 2)[1]
    source = Path("agentchange/hook_entry.py").read_text(encoding="utf-8")
    assert 'os.environ.get("PLUGIN_DATA")' in source
