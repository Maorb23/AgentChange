$ErrorActionPreference = "Stop"
$Python = if (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" } else { "python" }
& $Python "$PSScriptRoot/install_local.py"
