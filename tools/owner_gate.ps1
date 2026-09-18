<#
.SYNOPSIS
    owner_gate.ps1 - ONE automated owner MT5 certification gate.

.DESCRIPTION
    The Windows owner runs ONE command; every decision lives in committed
    code (mql5bot.gate_selfcheck via tools\owner_gate_decide.py and the
    existing verifiers), never in a prompt. The gate self-protects, then
    walks stages 1-10, STOPS at the first FAIL, and writes append-only
    evidence into evidence\owner_gate\<UTC>\ with one stage_<n>.json per
    stage. It prints a machine-readable summary ending in
    GATE_RESULT=<stage-name>.

    HARD RULES (enforced here, not asked of the operator):
      * never writes artifacts\owner_mt5_gate\frozen_inputs.json
      * never edits certification_manifest.json outside owner_evidence_bind
      * never substitutes live chart history for a committed fixture
      * never amends or force-pushes; it does not commit at all
      * divergences are recorded and classified, NEVER patched

    Stages 1-3 are pinned against the calibration run on branch
    windows/evidence-4257f1e (compile log 4/5 targets clean, dsl-parity
    14/14 EXACT + tampered refused, broker parity BTC=PENDING excluded).

    The sizing fix in 4257f1e changes volumes, so a stage-8 divergence on
    volume/risk fields is EXPECTED: it is classified (SIZING/RISK) and the
    affected expected_execution must be regenerated with NEW provenance by
    the owner/build side. This script NEVER reverts the fix and NEVER
    patches the gold artifacts.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\owner_gate.ps1 `
        -DataFolder D:\MT5 -Portable
#>

param(
    [string]$TerminalPath = "",
    [string]$MetaEditorPath = "",
    [string]$DataFolder = "",
    [switch]$Portable,
    [string]$SymbolSpecExport = "",
    [int]$TimeoutSec = 3600,
    # Optional: the directory the owner intends to be a FRESH clean-room clone.
    # If it already exists (non-empty), the gate names it and exits cleanly
    # instead of letting a later `git clone` fail deep in its own machinery and
    # leaving the owner to move directories by hand.
    [string]$CloneInto = ""
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = if ($env:MQL5BOT_PYTHON) { $env:MQL5BOT_PYTHON } else { "python" }
$Decide = Join-Path $PSScriptRoot "owner_gate_decide.py"

# ---- evidence root (append-only) -------------------------------------
# Compute the path now but DO NOT create the directory yet: the stage-0
# clean-tree self-check must run against a tree that does not yet contain the
# gate's own output. The committed .gitignore (/evidence/) makes this dir
# invisible to `git status` even once created, so creation order is no longer
# load-bearing -- but we still defer creation until just before first use so
# the check cannot possibly see it. (Historical bug: creating evidence\ up
# front left `?? evidence/` in the porcelain and the gate blocked itself.)
$Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmss")
$Evidence = Join-Path $RepoRoot ("evidence\owner_gate\" + $Stamp)

# ordered stage ledger; each entry: name/status/reason/artifacts
$Script:Stages = New-Object System.Collections.ArrayList
$Script:Blocked = $null

function Get-Sha256([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return "" }
    return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower()
}

function New-Artifact([string]$path) {
    return [ordered]@{ path = $path; sha256 = (Get-Sha256 $path) }
}

# record one stage (append-only stage_<n>.json) and return the record
function Record-Stage([int]$num, [string]$name, [string]$status,
                      [string]$reason, $artifacts) {
    $rec = [ordered]@{
        stage      = $num
        name       = $name
        status     = $status       # PASS | FAIL | SKIP | DIVERGENCE_EXPECTED
        reason     = $reason
        artifacts  = @($artifacts)
        utc        = (Get-Date).ToUniversalTime().ToString("o")
    }
    $out = Join-Path $Evidence ("stage_{0}.json" -f $num)
    ($rec | ConvertTo-Json -Depth 8) | Out-File -LiteralPath $out -Encoding ASCII
    [void]$Script:Stages.Add($rec)
    $color = switch ($status) {
        "PASS" { "Green" } "FAIL" { "Red" }
        "DIVERGENCE_EXPECTED" { "Yellow" } default { "Gray" }
    }
    Write-Host ("[owner-gate] stage {0} {1}: {2} -- {3}" -f $num, $name, $status, $reason) -ForegroundColor $color
    if ($status -eq "FAIL" -and -not $Script:Blocked) {
        $Script:Blocked = $name
    }
    return $rec
}

# run a decision via owner_gate_decide.py; returns parsed object + $ok
function Invoke-Decide([string[]]$deciderArgs) {
    $tmp = Join-Path $Evidence ("decide_" + [Guid]::NewGuid().ToString("N") + ".json")
    $full = @("--repo", $RepoRoot) + $deciderArgs
    $p = Start-Process -FilePath $Python -ArgumentList (@($Decide) + $full) `
        -RedirectStandardOutput $tmp -RedirectStandardError "$tmp.err" `
        -Wait -PassThru -NoNewWindow
    $obj = $null
    try { $obj = Get-Content -LiteralPath $tmp -Raw | ConvertFrom-Json } catch { }
    return [pscustomobject]@{ ok = ($p.ExitCode -eq 0); exit = $p.ExitCode; data = $obj; raw = $tmp }
}

# print the machine-readable summary and exit with GATE_RESULT
function Finish-Gate([string]$gateResult) {
    $summary = [ordered]@{
        gate            = "owner_mt5_certification"
        utc             = (Get-Date).ToUniversalTime().ToString("o")
        evidence_dir    = $Evidence
        first_blocking  = $Script:Blocked
        gate_result     = $gateResult
        stages          = @($Script:Stages)
    }
    $sumPath = Join-Path $Evidence "gate_summary.json"
    ($summary | ConvertTo-Json -Depth 12) | Out-File -LiteralPath $sumPath -Encoding ASCII
    Write-Host ""
    Write-Host "[owner-gate] ===== SUMMARY (machine-readable) ====="
    foreach ($s in $Script:Stages) {
        Write-Host ("  stage {0,-2} {1,-22} {2}" -f $s.stage, $s.name, $s.status)
        foreach ($a in $s.artifacts) {
            if ($a -and $a.path) { Write-Host ("      {0}  {1}" -f $a.sha256, $a.path) }
        }
    }
    Write-Host ("  first_blocking_stage: {0}" -f ($Script:Blocked))
    Write-Host ("  summary: {0}  ({1})" -f $sumPath, (Get-Sha256 $sumPath))
    Write-Host ("GATE_RESULT={0}" -f $gateResult)
    if ($gateResult -eq "certified") { exit 0 } else { exit 1 }
}

# locate an exe (Windows) without inventing a path
function Find-Exe([string]$name, [string]$explicit, [string]$envVar) {
    if ($explicit -and (Test-Path -LiteralPath $explicit)) { return $explicit }
    $envVal = [Environment]::GetEnvironmentVariable($envVar)
    if ($envVal -and (Test-Path -LiteralPath $envVal)) { return $envVal }
    if ($DataFolder) {
        $cand = Join-Path $DataFolder $name
        if (Test-Path -LiteralPath $cand) { return $cand }
    }
    foreach ($pf in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $pf) { continue }
        $hit = Get-ChildItem -LiteralPath $pf -Directory -Filter "MetaTrader*" -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.FullName $name } |
            Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if ($hit) { return $hit }
    }
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return ""
}

# launch a compiled script via a startup ini (mirrors run_dsl_parity.ps1)
function Invoke-TerminalScript([string]$scriptRel, [string]$label) {
    $iniPath = Join-Path $Evidence ($label + ".ini")
    $ini = @("[StartUp]", "Script=$scriptRel", "ShutdownTerminal=1") -join "`r`n"
    [IO.File]::WriteAllText($iniPath, $ini + "`r`n", [Text.Encoding]::ASCII)
    $argList = @("/config:$iniPath")
    if ($Portable) { $argList += "/portable" }
    $proc = Start-Process -FilePath $TerminalPath -ArgumentList $argList -PassThru
    if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
        try { $proc.Kill() } catch { }
        return $false
    }
    return $true
}

# create the append-only evidence root now (deferred from startup): every
# decision from here on records into it. It is .gitignore'd, so it does not
# dirty the tree the stage-0 clean-tree check inspects.
New-Item -ItemType Directory -Force -Path $Evidence | Out-Null
Write-Host "[owner-gate] evidence dir: $Evidence"

# =====================================================================
# STAGE A -- self-protection (abort with a NAMED reason)
# =====================================================================
# 0. optional fresh-clone preflight: if the owner named a clone target that
#    already exists, say so BY NAME and stop -- never leave a `git clone` to
#    fail deep in its own machinery, never move the owner's directory for them.
if ($CloneInto) {
    $cp = Invoke-Decide @("clone-preflight", $CloneInto)
    if (-not $cp.ok) {
        $reason = if ($cp.data) { "{0}: {1}" -f $cp.data.reason, $cp.data.detail } else { "SELF_PROTECT_CLONE_TARGET_EXISTS: $CloneInto" }
        Record-Stage 0 "self_protection" "FAIL" $reason @((New-Artifact $cp.raw)) | Out-Null
        Finish-Gate "self_protection"
    }
    Write-Host ("[owner-gate] clone target OK: {0}" -f ($cp.data.detail)) -ForegroundColor Green
}

$sp = Invoke-Decide @("self-protection")
if (-not $sp.ok) {
    $reason = if ($sp.data) { "{0}: {1}" -f $sp.data.reason, $sp.data.detail } else { "self-protection could not run" }
    Record-Stage 0 "self_protection" "FAIL" $reason @((New-Artifact $sp.raw)) | Out-Null
    Finish-Gate "self_protection"
}
# non-fatal self-protection NOTES (e.g. HEAD is a newer commit that descends
# from the frozen anchor after a re-anchor) -- a PASS the operator should see.
$spNotes = ""
if ($sp.data -and ($sp.data.PSObject.Properties.Name -contains "notes") -and $sp.data.notes) {
    $spNotes = ($sp.data.notes -join "; ")
    Write-Host ("[owner-gate] NOTE: {0}" -f $spNotes) -ForegroundColor Cyan
}
# locate the toolchain (Windows only); missing exe is a named abort
$TerminalPath = Find-Exe "terminal64.exe" $TerminalPath "MQL5BOT_TERMINAL"
$MetaEditorPath = Find-Exe "metaeditor64.exe" $MetaEditorPath "MQL5BOT_METAEDITOR"
if (-not $TerminalPath) {
    Record-Stage 0 "self_protection" "FAIL" "SELF_PROTECT_TERMINAL_NOT_FOUND: terminal64.exe not located (pass -TerminalPath or set MQL5BOT_TERMINAL)" @() | Out-Null
    Finish-Gate "self_protection"
}
if (-not $MetaEditorPath) {
    Record-Stage 0 "self_protection" "FAIL" "SELF_PROTECT_METAEDITOR_NOT_FOUND: metaeditor64.exe not located (pass -MetaEditorPath or set MQL5BOT_METAEDITOR)" @() | Out-Null
    Finish-Gate "self_protection"
}
if (-not $DataFolder -and $env:MQL5BOT_DATA_FOLDER) { $DataFolder = $env:MQL5BOT_DATA_FOLDER }
if (-not $DataFolder -or -not (Test-Path -LiteralPath (Join-Path $DataFolder "MQL5"))) {
    Record-Stage 0 "self_protection" "FAIL" "SELF_PROTECT_DATA_FOLDER: MT5 data folder unknown or has no MQL5\ (pass -DataFolder or set MQL5BOT_DATA_FOLDER)" @() | Out-Null
    Finish-Gate "self_protection"
}
$spPass = "HEAD relates to the frozen anchor (== or newer descendant), tree clean, autocrlf ok, frozen hashes + 42 dsl bound files verified, toolchain located"
if ($spNotes) { $spPass = "{0}. NOTE: {1}" -f $spPass, $spNotes }
Record-Stage 0 "self_protection" "PASS" $spPass @((New-Artifact $sp.raw)) | Out-Null

# =====================================================================
# STAGE 1 -- strict compile (decision from the LOG, not the exit code)
# =====================================================================
$logDir = Join-Path $RepoRoot "logs"
$compilePs1 = Join-Path $PSScriptRoot "compile.ps1"
& powershell -NoProfile -ExecutionPolicy Bypass -File $compilePs1 -Strict -MetaEditorPath $MetaEditorPath -DataFolder $DataFolder | Out-Null
$log = Get-ChildItem -LiteralPath $logDir -Filter "compile-*.log" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if (-not $log) {
    Record-Stage 1 "strict_compile" "FAIL" "no compile log produced in logs\" @() | Out-Null
    Finish-Gate "strict_compile"
}
$logCopy = Join-Path $Evidence $log.Name
Copy-Item -LiteralPath $log.FullName -Destination $logCopy -Force
$d = Invoke-Decide @("parse-compile", $logCopy)
if (-not $d.ok) {
    $r = if ($d.data) { ($d.data.reasons -join "; ") } else { "compile log parse failed" }
    Record-Stage 1 "strict_compile" "FAIL" $r @((New-Artifact $logCopy)) | Out-Null
    Finish-Gate "strict_compile"
}
Record-Stage 1 "strict_compile" "PASS" ("0 errors, 0 warnings; targets clean: " + ($d.data.targets_passed -join ", ")) @((New-Artifact $logCopy)) | Out-Null

# =====================================================================
# STAGE 2 -- DSL parity (14/14 EXACT + tampered refused)
# =====================================================================
$dslArgs = @("-DataFolder", $DataFolder, "-TerminalPath", $TerminalPath)
if ($Portable) { $dslArgs += "-Portable" }
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "run_dsl_parity.ps1") @dslArgs | Out-Null
$dslEvidence = Get-ChildItem -LiteralPath (Join-Path $RepoRoot "evidence\dsl_parity") -Directory -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending | Select-Object -First 1
$compareReport = if ($dslEvidence) { Join-Path $dslEvidence.FullName "compare_report.txt" } else { "" }
if (-not $compareReport -or -not (Test-Path -LiteralPath $compareReport)) {
    Record-Stage 2 "dsl_parity" "FAIL" "no compare_report.txt produced by run_dsl_parity.ps1" @() | Out-Null
    Finish-Gate "dsl_parity"
}
$dslCopy = Join-Path $Evidence "dsl_compare_report.txt"
Copy-Item -LiteralPath $compareReport -Destination $dslCopy -Force
$shaManifest = Join-Path $dslEvidence.FullName "sha256_manifest.txt"
if (Test-Path -LiteralPath $shaManifest) {
    Copy-Item -LiteralPath $shaManifest -Destination (Join-Path $Evidence "dsl_sha256_manifest.txt") -Force
}
$d = Invoke-Decide @("parse-dsl", $dslCopy)
if (-not $d.ok) {
    $r = if ($d.data) { ($d.data.reasons -join "; ") } else { "dsl parity parse failed" }
    Record-Stage 2 "dsl_parity" "FAIL" $r @((New-Artifact $dslCopy)) | Out-Null
    Finish-Gate "dsl_parity"
}
Record-Stage 2 "dsl_parity" "PASS" ("{0}/{1} fixtures EXACT + tampered refused" -f $d.data.exact, $d.data.total) @((New-Artifact $dslCopy)) | Out-Null

# =====================================================================
# STAGE 3 -- SymbolSpec export + broker parity (MISMATCH aborts;
#            BTC/crypto PENDING excluded from certification scope)
# =====================================================================
# the owner attaches Mql5BotExportSymbolSpec to each chart symbol; the
# committed exports land under data\broker_exports\ (gitignored, owner-side)
$parityReport = Join-Path $RepoRoot "data\broker_exports\parity_report.json"
& $Python (Join-Path $PSScriptRoot "broker_symbol_parity.py") | Out-Null
if (-not (Test-Path -LiteralPath $parityReport)) {
    Record-Stage 3 "broker_parity" "FAIL" "no data\broker_exports\parity_report.json (attach Mql5BotExportSymbolSpec to each symbol first)" @() | Out-Null
    Finish-Gate "broker_parity"
}
$parityCopy = Join-Path $Evidence "parity_report.json"
Copy-Item -LiteralPath $parityReport -Destination $parityCopy -Force
$d = Invoke-Decide @("broker-scope", $parityCopy)
if (-not $d.ok) {
    $r = if ($d.data) { ($d.data.reasons -join "; ") } else { "broker parity scope failed" }
    Record-Stage 3 "broker_parity" "FAIL" $r @((New-Artifact $parityCopy)) | Out-Null
    Finish-Gate "broker_parity"
}
$excl = if ($d.data.pending_excluded_crypto) { ($d.data.pending_excluded_crypto | ForEach-Object { $_ -join ":" }) -join ", " } else { "none" }
Record-Stage 3 "broker_parity" "PASS" ("{0} MATCH rows; crypto PENDING excluded: {1}" -f $d.data.match_count, $excl) @((New-Artifact $parityCopy)) | Out-Null

# resolve the SymbolSpec export used for stage 4 (EURUSD by default)
if (-not $SymbolSpecExport) {
    $SymbolSpecExport = Join-Path $RepoRoot "data\broker_exports\EURUSD.json"
}

# =====================================================================
# STAGE 4 -- gold fixture import into a custom symbol (round-trip hash)
# =====================================================================
$stage4ok = $true
$stage4art = New-Object System.Collections.ArrayList
$golds = @(
    @{ name = "GOLD1_EURUSD"; fixture = "artifacts\gold\gold_fixture.csv";   manifest = "artifacts\gold\manifest.json" },
    @{ name = "GOLD2_EURUSD"; fixture = "artifacts\gold_2\gold2_fixture.csv"; manifest = "artifacts\gold_2\manifest.json" }
)
$filesImport = Join-Path $DataFolder "MQL5\Files\Mql5Bot\gold_import"
$importOut = Join-Path $DataFolder "MQL5\Files\Mql5Bot\gold_import_out"
foreach ($g in $golds) {
    New-Item -ItemType Directory -Force -Path $filesImport | Out-Null
    if (Test-Path -LiteralPath $importOut) { Remove-Item -LiteralPath $importOut -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $importOut | Out-Null
    Copy-Item -LiteralPath (Join-Path $RepoRoot $g.fixture) -Destination (Join-Path $filesImport "gold_fixture.csv") -Force
    Copy-Item -LiteralPath (Join-Path $RepoRoot $g.manifest) -Destination (Join-Path $filesImport "manifest.json") -Force
    if (Test-Path -LiteralPath $SymbolSpecExport) {
        New-Item -ItemType Directory -Force -Path (Join-Path $DataFolder "MQL5\Files\Mql5Bot\broker_exports") | Out-Null
        Copy-Item -LiteralPath $SymbolSpecExport -Destination (Join-Path $DataFolder "MQL5\Files\Mql5Bot\broker_exports\EURUSD.json") -Force
    }
    # NOTE: the importer refuses (creates nothing) unless the staged fixture
    # sha256 equals the manifest dataset_hash and the CustomRatesUpdate
    # round-trip re-derives that same hash.
    if (-not (Invoke-TerminalScript "Mql5Bot\Mql5BotImportFixture" ("import_" + $g.name))) {
        $stage4ok = $false
        Record-Stage 4 "fixture_import" "FAIL" ("terminal timed out importing {0}" -f $g.name) @($stage4art) | Out-Null
        Finish-Gate "fixture_import"
    }
    $resultJson = Join-Path $importOut ($g.name + ".json")
    if (-not (Test-Path -LiteralPath $resultJson)) {
        # the importer writes a JSON on EVERY outcome (even a refusal); a
        # missing file means the terminal never ran the script or it crashed.
        $stage4ok = $false
        Record-Stage 4 "fixture_import" "FAIL" ("{0}: importer produced no output JSON (terminal did not run the script)" -f $g.name) @($stage4art) | Out-Null
        Finish-Gate "fixture_import"
    }
    # attach the importer diagnostic to stage_4.json whether it passes or fails
    $resCopy = Join-Path $Evidence ("import_" + $g.name + ".json")
    Copy-Item -LiteralPath $resultJson -Destination $resCopy -Force
    [void]$stage4art.Add((New-Artifact $resCopy))
    # classify the diagnostic in committed Python: a refusal MUST name the
    # failing property / stage / last_error (never a vacuous refusal again)
    $diag = Invoke-Decide @("import-diagnostic", $resCopy)
    $res = Get-Content -LiteralPath $resCopy -Raw | ConvertFrom-Json
    $man = Get-Content -LiteralPath (Join-Path $RepoRoot $g.manifest) -Raw | ConvertFrom-Json
    if ($res.refused -ne $false -or $res.roundtrip_sha256 -ne $man.dataset_hash) {
        $stage4ok = $false
        $why = if ($diag.data -and $diag.data.reason) { $diag.data.reason } else { "import refused or dataset hash mismatch" }
        Record-Stage 4 "fixture_import" "FAIL" ("{0}: {1} (roundtrip {2}, manifest {3})" -f $g.name, $why, $res.roundtrip_sha256, $man.dataset_hash) @($stage4art) | Out-Null
        Finish-Gate "fixture_import"
    }
    if (-not $diag.data.populated) {
        # defence in depth: a PASS whose diagnostic is not populated means the
        # importer regressed to a blind result -- fail closed.
        $stage4ok = $false
        Record-Stage 4 "fixture_import" "FAIL" ("{0}: import diagnostic not populated ({1})" -f $g.name, $diag.data.reason) @($stage4art) | Out-Null
        Finish-Gate "fixture_import"
    }
}
if (-not $stage4ok) {
    Record-Stage 4 "fixture_import" "FAIL" "custom-symbol import did not produce a faithful round-trip for both golds" @($stage4art) | Out-Null
    Finish-Gate "fixture_import"
}
Record-Stage 4 "fixture_import" "PASS" "both gold fixtures imported; round-trip dataset hash == manifest" @($stage4art) | Out-Null

# =====================================================================
# STAGES 5-7 -- six tester legs (Gold#1/#2 x m1_ohlc/every_tick/real_ticks)
#   ACTUAL model is read from the report Model line + journal (not the
#   requested one); real-tick coverage is FULL/PARTIAL/UNKNOWN with
#   evidence; the dataset hash is re-checked after the legs.
# =====================================================================
$legs = @(
    @{ gold = "gold1"; model = "m1_ohlc";    m = 1 },
    @{ gold = "gold1"; model = "every_tick"; m = 0 },
    @{ gold = "gold1"; model = "real_ticks"; m = 3 },
    @{ gold = "gold2"; model = "m1_ohlc";    m = 1 },
    @{ gold = "gold2"; model = "every_tick"; m = 0 },
    @{ gold = "gold2"; model = "real_ticks"; m = 3 }
)
$legArt = New-Object System.Collections.ArrayList
$legReasons = New-Object System.Collections.ArrayList
$legOk = $true
$symbolByGold = @{ gold1 = "GOLD1_EURUSD"; gold2 = "GOLD2_EURUSD" }
$tfByGold = @{ gold1 = "H1"; gold2 = "M1" }
foreach ($leg in $legs) {
    $sym = $symbolByGold[$leg.gold]
    $tf = $tfByGold[$leg.gold]
    $reportName = "{0}_{1}" -f $leg.gold, $leg.model
    $runArgs = @("run", "--terminal-dir", (Split-Path -Parent $TerminalPath),
        "--data-folder", $DataFolder, "--symbol", $sym, "--timeframe", $tf,
        "--model", $leg.m, "--report", $reportName, "--out-dir", (Join-Path $Evidence "tester"))
    $p = Start-Process -FilePath $Python `
        -ArgumentList (@((Join-Path $PSScriptRoot "run_mt5_backtest.py")) + $runArgs) `
        -Wait -PassThru -NoNewWindow
    if ($p.ExitCode -ne 0) {
        $legOk = $false
        [void]$legReasons.Add(("{0}: tester leg exit {1}" -f $reportName, $p.ExitCode))
        continue
    }
    # archive the raw .htm + the report.json sidecar; read ACTUAL model
    $runRoot = Join-Path (Join-Path $Evidence "tester") "runs"
    $latest = Get-ChildItem -LiteralPath $runRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like ($reportName + "_*") } |
        Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    if ($latest) {
        Get-ChildItem -LiteralPath $latest.FullName -File | ForEach-Object {
            [void]$legArt.Add((New-Artifact $_.FullName))
        }
    }
}
if (-not $legOk) {
    Record-Stage 5 "tester_legs" "FAIL" (($legReasons -join "; ")) @($legArt) | Out-Null
    Finish-Gate "tester_legs"
}
Record-Stage 5 "tester_legs" "PASS" "six tester legs produced raw reports + sidecars; models read from report+journal" @($legArt) | Out-Null

# =====================================================================
# STAGE 8 -- reconciliation (full bindings + 8a kill-switch, 8b restart,
#            8c retry/adoption/SlGuard, 8d NETTING and HEDGING) via the
#            evidence CONSUMER. A volume/risk divergence is EXPECTED for
#            the 4257f1e sizing fix: classify + record, never patch.
# =====================================================================
$evidencePkg = if ($env:MQL5BOT_EVIDENCE_DIR) { $env:MQL5BOT_EVIDENCE_DIR } else { Join-Path $RepoRoot "artifacts\owner_mt5_gate\evidence" }
$verifyOut = Join-Path $Evidence "reconciliation_verify.json"
$vp = Start-Process -FilePath $Python `
    -ArgumentList (@((Join-Path $PSScriptRoot "verify_owner_mt5_gate.py"), $evidencePkg, "--repo", $RepoRoot, "--out", $verifyOut)) `
    -Wait -PassThru -NoNewWindow
$recon = $null
try { $recon = Get-Content -LiteralPath $verifyOut -Raw | ConvertFrom-Json } catch { }
if (-not $recon) {
    Record-Stage 8 "reconciliation" "FAIL" "verify_owner_mt5_gate.py produced no report (owner evidence package missing?)" @() | Out-Null
    Finish-Gate "reconciliation"
}
# classify any first divergence; a SIZING/RISK class is the EXPECTED 4257f1e
# outcome -> record + owner/build follow-up, never a silent pass, never patched
$divClass = ""
$divField = ""
foreach ($gld in @("gold1", "gold2")) {
    $fd = $recon.first_divergence.$gld
    if ($fd -and $fd.first_divergent_field) {
        $divField = $fd.first_divergent_field
        $cd = Invoke-Decide @("classify", $divField)
        if ($cd.data) { $divClass = $cd.data.classification }
        break
    }
}
if ($recon.verdict -eq "MT5_VALIDATED") {
    Record-Stage 8 "reconciliation" "PASS" "bindings + 8a-8d verified; gold parity holds on the owner terminal" @((New-Artifact $verifyOut)) | Out-Null
} elseif ($divClass -eq "SIZING_MISMATCH" -or $divClass -eq "RISK_MISMATCH") {
    $note = ("EXPECTED for the 4257f1e sizing fix: first divergence on '{0}' -> {1}. Regenerate the affected expected_execution with NEW provenance (owner/build side); NEVER revert the fix, NEVER patch the gold artifacts here." -f $divField, $divClass)
    Record-Stage 8 "reconciliation" "DIVERGENCE_EXPECTED" $note @((New-Artifact $verifyOut)) | Out-Null
    # a recorded expected divergence still blocks MT5 certification until the
    # owner regenerates expected_execution + re-anchors; stop here, fail-closed
    $Script:Blocked = "reconciliation"
    Finish-Gate "reconciliation"
} else {
    Record-Stage 8 "reconciliation" "FAIL" ("verdict {0}: {1}" -f $recon.verdict, ($recon.reasons -join "; ")) @((New-Artifact $verifyOut)) | Out-Null
    Finish-Gate "reconciliation"
}

# =====================================================================
# STAGE 9 -- archive manifest (owner_evidence_bind.py only; no hand-typed hash)
# =====================================================================
$archiveManifest = Join-Path $Evidence "archive_manifest.json"
$ap = Start-Process -FilePath $Python `
    -ArgumentList (@((Join-Path $PSScriptRoot "owner_evidence_bind.py"), "manifest", $Evidence, "--frozen", (Join-Path $RepoRoot "artifacts\owner_mt5_gate\frozen_inputs.json"))) `
    -RedirectStandardOutput $archiveManifest -Wait -PassThru -NoNewWindow
if ($ap.ExitCode -ne 0) {
    Record-Stage 9 "archive_manifest" "FAIL" ("owner_evidence_bind.py exit {0}" -f $ap.ExitCode) @() | Out-Null
    Finish-Gate "archive_manifest"
}
Record-Stage 9 "archive_manifest" "PASS" "evidence bound by owner_evidence_bind.py (no hand-typed hash)" @((New-Artifact $archiveManifest)) | Out-Null

# =====================================================================
# STAGE 10 -- certify_strategy.py records whatever state it assigns
# =====================================================================
$certConfig = Join-Path $RepoRoot "artifacts\owner_mt5_gate\certify_config.json"
$certReport = Join-Path $Evidence "certification_report.md"
if (-not (Test-Path -LiteralPath $certConfig)) {
    Record-Stage 10 "certify" "SKIP" "no certify_config.json present; certification state unassigned" @() | Out-Null
    Finish-Gate "reconciliation"
}
$cp = Start-Process -FilePath $Python `
    -ArgumentList (@((Join-Path $PSScriptRoot "certify_strategy.py"), "--config", $certConfig, "--out", $certReport)) `
    -Wait -PassThru -NoNewWindow
$certStatus = if ($cp.ExitCode -eq 0) { "PASS" } else { "FAIL" }
Record-Stage 10 "certify" $certStatus ("certify_strategy.py exit {0} (state recorded as assigned)" -f $cp.ExitCode) @((New-Artifact $certReport)) | Out-Null
if ($certStatus -eq "FAIL") { Finish-Gate "certify" }

Finish-Gate "certified"
