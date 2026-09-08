[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $RepoAnchor,
    [Parameter(Mandatory)] [string] $Baseline,
    [string] $ExpectedHead,
    [Parameter(Mandatory)] [ValidateSet("READ-ONLY", "WRITE")] [string] $Mode,
    [Parameter(Mandatory)] [string] $Worktree,
    [string] $Branch,
    [Parameter(Mandatory)] [ValidateSet("fast", "core", "ha-adapter", "ha-framework", "ha-source", "packaging")] [string] $Profile,
    [string] $CorePython,
    [string] $WslDistro,
    [string] $WslWorktree,
    [string] $HaEnvironment,
    [string] $ExpectedOrigin = "https://github.com/vmshops/controlel.git"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Fail([string] $Message) {
    Write-Error "PREFLIGHT: $Message"
    Write-Output "=== PREFLIGHT FAIL ==="
    exit 1
}

try {
    $anchor = [IO.Path]::GetFullPath($RepoAnchor)
    $execution = [IO.Path]::GetFullPath($Worktree)
    if (-not (Test-Path -LiteralPath $anchor -PathType Container)) { Fail "repository anchor does not exist: $anchor" }
    if (-not (Test-Path -LiteralPath $execution -PathType Container)) { Fail "execution worktree does not exist: $execution" }
    if ($anchor -eq $execution) { Fail "execution worktree must be separate from the repository anchor" }

    $origin = (& git -C $execution remote get-url origin).Trim()
    if ($origin -ne $ExpectedOrigin) { Fail "unexpected origin: $origin" }
    $anchorOrigin = (& git -C $anchor remote get-url origin).Trim()
    if ($anchorOrigin -ne $ExpectedOrigin) { Fail "anchor has unexpected origin: $anchorOrigin" }
    & git -C $execution cat-file -e "$Baseline^{commit}" 2>$null
    if ($LASTEXITCODE -ne 0) { Fail "baseline commit is unavailable: $Baseline" }
    if ([string]::IsNullOrWhiteSpace($ExpectedHead)) { $ExpectedHead = $Baseline }
    & git -C $execution cat-file -e "$ExpectedHead^{commit}" 2>$null
    if ($LASTEXITCODE -ne 0) { Fail "expected HEAD commit is unavailable: $ExpectedHead" }
    $head = (& git -C $execution rev-parse HEAD).Trim()
    if ($head -ne $ExpectedHead) { Fail "worktree HEAD $head does not equal expected HEAD $ExpectedHead" }
    $status = & git -C $execution status --porcelain
    if ($status) { Fail "execution worktree is dirty" }
    $gitDir = (& git -C $execution rev-parse --git-dir).Trim()
    $active = @("MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD") | Where-Object { Test-Path -LiteralPath (Join-Path $gitDir $_) }
    if ($active) { Fail "active Git operation: $($active -join ', ')" }

    if ($Mode -eq "WRITE") {
        if ([string]::IsNullOrWhiteSpace($Branch)) { Fail "WRITE requires an explicit branch" }
        if ($Branch -in @("main", "master")) { Fail "WRITE refuses protected branch: $Branch" }
        $actualBranch = (& git -C $execution branch --show-current).Trim()
        if ($actualBranch -ne $Branch) { Fail "worktree branch $actualBranch does not equal requested branch $Branch" }
    } elseif ($Branch) { Fail "READ-ONLY does not accept a branch" }

    if ($Profile -in @("fast", "core", "packaging")) {
        if ([string]::IsNullOrWhiteSpace($CorePython) -or -not (Test-Path -LiteralPath $CorePython -PathType Leaf)) { Fail "a valid CorePython is required for $Profile" }
        $version = (& $CorePython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
        if ($version -ne "3.14") { Fail "CorePython must be Python 3.14.x, got $version" }
    }
    if ($Profile -like "ha-*") {
        if ([string]::IsNullOrWhiteSpace($WslDistro)) { Fail "WSL distro is required for $Profile" }
        if ([string]::IsNullOrWhiteSpace($WslWorktree)) { Fail "WSL worktree path is required for $Profile" }
        if ([string]::IsNullOrWhiteSpace($HaEnvironment)) { Fail "HA environment path is required for $Profile" }
        & wsl.exe -d $WslDistro -- bash "$WslWorktree/scripts/agent/ha-test.sh" --worktree "$WslWorktree" --baseline "$Baseline" --profile $(if ($Profile -eq "ha-source") { "source-candidate" } else { "checked-out-wheel" }) --environment "$HaEnvironment" --validate
        if ($LASTEXITCODE -ne 0) { Fail "HA environment provenance/fingerprint is invalid" }
    }
    Write-Output "=== PREFLIGHT OK ==="
} catch {
    if ($_.Exception.Message -notlike "*PREFLIGHT:*") { Write-Error "PREFLIGHT: $($_.Exception.Message)"; Write-Output "=== PREFLIGHT FAIL ===" }
    exit 1
}
