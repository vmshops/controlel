[CmdletBinding()]
param(
    [Parameter(Mandatory)] [ValidateSet("fast", "core", "ha-adapter", "ha-framework", "ha-source", "packaging")] [string] $Profile,
    [Parameter(Mandatory)] [string] $RepoAnchor,
    [Parameter(Mandatory)] [string] $Baseline,
    [string] $ExpectedHead,
    [Parameter(Mandatory)] [ValidateSet("READ-ONLY", "WRITE")] [string] $Mode,
    [Parameter(Mandatory)] [string] $Worktree,
    [string] $Branch,
    [string] $CorePython,
    [string] $WslDistro,
    [string] $WslWorktree,
    [string] $HaEnvironment
)

$preflight = Join-Path $PSScriptRoot "preflight.ps1"
& $preflight @PSBoundParameters
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

switch ($Profile) {
    "fast" { & $CorePython -m pytest tests/architecture; break }
    "core" { & $CorePython -m pytest tests; break }
    "packaging" { & $CorePython -m pytest tests/packaging; break }
    "ha-adapter" {
        & wsl.exe -d $WslDistro -- bash "$WslWorktree/scripts/agent/ha-test.sh" --worktree "$WslWorktree" --baseline "$Baseline" --profile checked-out-wheel --environment "$HaEnvironment" -- tests/integrations/home_assistant
        break
    }
    "ha-framework" {
        & wsl.exe -d $WslDistro -- bash "$WslWorktree/scripts/agent/ha-test.sh" --worktree "$WslWorktree" --baseline "$Baseline" --profile checked-out-wheel --environment "$HaEnvironment" -- tests/integrations/home_assistant/framework
        break
    }
    "ha-source" {
        & wsl.exe -d $WslDistro -- bash "$WslWorktree/scripts/agent/ha-test.sh" --worktree "$WslWorktree" --baseline "$Baseline" --profile source-candidate --environment "$HaEnvironment" -- tests/integrations/home_assistant/test_manifest_and_boundary.py
        break
    }
}
exit $LASTEXITCODE
