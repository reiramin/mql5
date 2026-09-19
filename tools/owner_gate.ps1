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

# STAGE 5 R1 ROOT CAUSE: Start-Process flattens an -ArgumentList ARRAY into ONE
# command-line string by joining the elements with a single space and does NOT
# quote an element that contains a space -- so "C:\Program Files\MetaTrader 5"
# arrived at python as THREE tokens and argparse rejected "Files\MetaTrader 5"
# (all six stage-5 legs exit 2, empty artifacts array). Every external process
# the gate STARTS is now handed an argument array whose every element is quoted
# per the Windows CommandLineToArgvW rules, so a path with a space can never
# re-split, and an empty element is passed as a literal "" (the R5 fix, folded
# in here). The PowerShell call operator (&) used by stages 1-3 passes each
# array element to the child verbatim and needs no quoting; only Start-Process
# does. ConvertTo-ProcArg is the single quoting rule; Get-ProcArgs maps a whole
# array through it so no call site hand-builds a command string.
function ConvertTo-ProcArg([AllowNull()][string]$a) {
    if ([string]::IsNullOrEmpty($a)) { return '""' }
    if ($a -notmatch '[ \t\n\v"]') { return $a }
    $sb = [System.Text.StringBuilder]::new()
    [void]$sb.Append('"')
    for ($i = 0; $i -lt $a.Length; $i++) {
        $bs = 0
        while ($i -lt $a.Length -and $a[$i] -eq '\') { $bs++; $i++ }
        if ($i -eq $a.Length) { [void]$sb.Append('\' * ($bs * 2)); break }
        elseif ($a[$i] -eq '"') { [void]$sb.Append('\' * ($bs * 2 + 1)); [void]$sb.Append('"') }
        else { [void]$sb.Append('\' * $bs); [void]$sb.Append($a[$i]) }
    }
    [void]$sb.Append('"')
    return $sb.ToString()
}
function Get-ProcArgs([string[]]$items) {
    return @($items | ForEach-Object { ConvertTo-ProcArg $_ })
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
    # R5 ROOT CAUSE (gate_run7): Start-Process REFUSES an -ArgumentList that
    # contains a $null or "" element ("Cannot validate argument on parameter
    # 'ArgumentList'") -- the stage-4 outcome call passed --log-excerpt with
    # an EMPTY path when the import JSON existed, and the gate died with no
    # verdict. Get-ProcArgs/ConvertTo-ProcArg pass empty elements as a literal
    # quoted "" (and quote any path with a space -- the STAGE 5 R1 root cause),
    # so the child still sees an empty argument and the gate can never crash
    # verdictless here again.
    $argv = Get-ProcArgs (@($Decide) + $full)
    $p = Start-Process -FilePath $Python -ArgumentList $argv `
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

# =====================================================================
# STRUCTURAL VERDICT CONTRACT (R5): the gate ALWAYS ends with a
# machine-readable verdict -- stage_<n>.json for the stage in progress,
# gate_summary.json, and a GATE_RESULT= line -- even on an UNHANDLED
# error anywhere in the run. Enter-Stage tracks which stage is in
# progress; the script-scope trap below converts any unhandled
# terminating error into a recorded FAIL for that stage and finishes
# the gate instead of dying verdictless (the gate_run7 defect: a
# Start-Process parameter error at stage 4 exited 1 with no stage_4.json,
# no summary and no GATE_RESULT line).
# =====================================================================
$Script:CurStageNum = 0
$Script:CurStageName = "self_protection"

function Enter-Stage([int]$num, [string]$name) {
    $Script:CurStageNum = $num
    $Script:CurStageName = $name
    # test hook: MQL5BOT_GATE_FAULT=<stage-name> injects an unhandled throw
    # at that stage boundary so the always-a-verdict contract is testable
    # end-to-end (never set in a real owner run).
    if ($env:MQL5BOT_GATE_FAULT -and ($env:MQL5BOT_GATE_FAULT -eq $name)) {
        throw ("FAULT_INJECTION: forced unhandled error in stage " + $name)
    }
}

trap {
    $failMsg = "UNHANDLED_ERROR: gate crashed without a recorded reason"
    try {
        $failMsg = ("UNHANDLED_ERROR: {0} (script line {1})" -f `
            $_.Exception.Message, $_.InvocationInfo.ScriptLineNumber)
    } catch { }
    try {
        if (-not (Test-Path -LiteralPath $Evidence)) {
            New-Item -ItemType Directory -Force -Path $Evidence | Out-Null
        }
        Record-Stage $Script:CurStageNum $Script:CurStageName "FAIL" $failMsg @() | Out-Null
        Finish-Gate $Script:CurStageName    # writes gate_summary.json, prints GATE_RESULT=, exits 1
    } catch {
        # last resort: even a broken evidence dir still yields the verdict line
        Write-Host ("GATE_RESULT={0}" -f $Script:CurStageName)
        exit 1
    }
    exit 1
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

# launch a compiled script via a startup ini (mirrors run_dsl_parity.ps1).
# $presetName, when set, is a *.set file in MQL5\Presets carrying the script
# inputs (symbol name, explicit output path, ...) -- this is how the gate tells
# the importer WHICH gold it is and EXACTLY where to write its JSON, instead of
# relying on the script's compiled-in defaults. Returns launch status so the
# caller can tell "never launched" from "ran but produced nothing".
function Invoke-TerminalScript([string]$scriptRel, [string]$label, [string]$presetName = "") {
    $iniPath = Join-Path $Evidence ($label + ".ini")
    $iniLines = @("[StartUp]", "Script=$scriptRel")
    if ($presetName) { $iniLines += "ScriptParameters=$presetName" }
    $iniLines += "ShutdownTerminal=1"
    [IO.File]::WriteAllText($iniPath, ($iniLines -join "`r`n") + "`r`n", [Text.Encoding]::ASCII)
    # /config:<ini> carries the evidence path, which lives under $RepoRoot and
    # can contain a space -- quote it (STAGE 5 R1) so the terminal receives one
    # argument, not "/config:C:\Program" + "Files\...".
    $argList = @("/config:$iniPath")
    if ($Portable) { $argList += "/portable" }
    try {
        $proc = Start-Process -FilePath $TerminalPath -ArgumentList (Get-ProcArgs $argList) -PassThru
    } catch {
        return [pscustomobject]@{ launched = $false; exited = $false }
    }
    if (-not $proc) { return [pscustomobject]@{ launched = $false; exited = $false } }
    $exited = $true
    if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
        try { $proc.Kill() } catch { }
        $exited = $false
    }
    return [pscustomobject]@{ launched = $true; exited = $exited }
}

# backstop for stage 4: when the importer wrote no JSON, grep the MT5 logs for
# its own Print lines (prefixed "Mql5BotImportFixture" / "[import]" -- the
# importer's FIRST action is a "[import] STARTUP ..." banner naming every
# resolved input, so these lines prove WHICH inputs the run actually got) so
# the cause lands in the evidence dir regardless. $extraLines (e.g. stray
# default-path outputs the gate spotted) are written FIRST. Writes an excerpt
# file and returns its artifact (always -- an empty excerpt still records
# "nothing found", which is itself evidence).
function Save-ImporterLog([string]$name, $extraLines = $null) {
    $dirs = @((Join-Path $DataFolder "MQL5\Logs"), (Join-Path $DataFolder "logs"))
    $lines = New-Object System.Collections.ArrayList
    foreach ($d in $dirs) {
        if (-not (Test-Path -LiteralPath $d)) { continue }
        Get-ChildItem -LiteralPath $d -Filter "*.log" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 3 |
            ForEach-Object {
                try {
                    Select-String -LiteralPath $_.FullName `
                        -Pattern "Mql5BotImportFixture", "\[import\]" `
                        -ErrorAction SilentlyContinue |
                        ForEach-Object { [void]$lines.Add(("{0}: {1}" -f (Split-Path -Leaf $_.Path), $_.Line.Trim())) }
                } catch { }
            }
    }
    $all = New-Object System.Collections.ArrayList
    if ($extraLines) {
        foreach ($x in @($extraLines)) { if ($x) { [void]$all.Add([string]$x) } }
    }
    if ($lines.Count -eq 0) {
        [void]$all.Add("(no Mql5BotImportFixture lines found in MT5 logs under " + $DataFolder + ")")
    } else {
        foreach ($l in $lines) { [void]$all.Add($l) }
    }
    $out = Join-Path $Evidence ("import_" + $name + "_terminal_log.txt")
    [IO.File]::WriteAllText($out, (($all -join "`r`n") + "`r`n"), [Text.Encoding]::ASCII)
    return (New-Artifact $out)
}

# stage-5 tester-journal excerpt: grep the most recent tester/agent/terminal
# logs for the lines that state WHICH model actually ran and the tick/history
# provenance (the evidence read_actual_model + classify_real_tick_coverage
# decide on). Always returns an artifact -- an empty excerpt still records
# "nothing found", which is itself evidence for a failing leg. $reportName and
# $symbol narrow the grep so a leg's own lines are captured.
function Save-TesterLog([string]$name, [string]$reportName, [string]$symbol) {
    # STAGE 5 R2 DEFECT 1: the Strategy Tester's OWN log lives in a NESTED
    # directory (Tester\Agent-127.0.0.1-3000\logs\), not Tester\logs\, so it was
    # never read. Search the Tester ROOT with -Recurse so the agent log is
    # enumerated too (the Tester root recursion subsumes Tester\logs\).
    $dirs = @((Join-Path $DataFolder "Tester"),
              (Join-Path $DataFolder "MQL5\Logs"),
              (Join-Path $DataFolder "logs"))
    $patterns = @([regex]::Escape($reportName), [regex]::Escape($symbol),
                  "real tick", "generated tick", "history quality",
                  "modelling", "modeling", "1 minute OHLC", "Every tick",
                  "Real ticks", "\bmodel\b", "ticks")
    $lines = New-Object System.Collections.ArrayList
    foreach ($d in $dirs) {
        if (-not (Test-Path -LiteralPath $d)) { continue }
        Get-ChildItem -LiteralPath $d -Filter "*.log" -Recurse -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 5 |
            ForEach-Object {
                try {
                    Select-String -LiteralPath $_.FullName -Pattern $patterns `
                        -ErrorAction SilentlyContinue |
                        ForEach-Object { [void]$lines.Add(("{0}: {1}" -f (Split-Path -Leaf $_.Path), $_.Line.Trim())) }
                } catch { }
            }
    }
    if ($lines.Count -eq 0) {
        [void]$lines.Add("(no tester-journal lines for " + $reportName +
            " / " + $symbol + " found in MT5 logs under " + $DataFolder + ")")
    }
    $out = Join-Path $Evidence ("tester_" + $name + "_journal.txt")
    [IO.File]::WriteAllText($out, (($lines -join "`r`n") + "`r`n"), [Text.Encoding]::ASCII)
    return (New-Artifact $out)
}

# STAGE 5 R2 DEFECT 2: the Save-TesterLog pattern filter is built for modelling
# quality (real tick / modelling / history quality / ...) and CANNOT match the
# lines that explain a FAILURE ("no history", EA init failures, file errors).
# When a leg fails, capture the UNFILTERED tail (last 200 lines) of every tester
# log TOUCHED during that leg's window ($since = the leg's launch time), so a
# failing leg never attaches only artifacts that cannot explain it -- the
# STAGE 5 R1 rule. A passing leg keeps only the filtered Save-TesterLog excerpt.
function Save-TesterFailLog([string]$name, [datetime]$since) {
    $dirs = @((Join-Path $DataFolder "Tester"),
              (Join-Path $DataFolder "MQL5\Logs"),
              (Join-Path $DataFolder "logs"))
    $lines = New-Object System.Collections.ArrayList
    foreach ($d in $dirs) {
        if (-not (Test-Path -LiteralPath $d)) { continue }
        Get-ChildItem -LiteralPath $d -Filter "*.log" -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -ge $since } |
            Sort-Object LastWriteTimeUtc |
            ForEach-Object {
                [void]$lines.Add("===== " + $_.FullName + " (last 200 lines) =====")
                try {
                    Get-Content -LiteralPath $_.FullName -Tail 200 -ErrorAction SilentlyContinue |
                        ForEach-Object { [void]$lines.Add($_) }
                } catch { }
            }
    }
    if ($lines.Count -eq 0) {
        [void]$lines.Add("(no tester log was written during this leg's window under " +
            $DataFolder + " -- the terminal produced no tester log for " + $name + ")")
    }
    $out = Join-Path $Evidence ("tester_" + $name + "_journal_tail.txt")
    [IO.File]::WriteAllText($out, (($lines -join "`r`n") + "`r`n"), [Text.Encoding]::ASCII)
    return (New-Artifact $out)
}

# create the append-only evidence root now (deferred from startup): every
# decision from here on records into it. It is .gitignore'd, so it does not
# dirty the tree the stage-0 clean-tree check inspects.
New-Item -ItemType Directory -Force -Path $Evidence | Out-Null
Write-Host "[owner-gate] evidence dir: $Evidence"
Enter-Stage 0 "self_protection"

# =====================================================================
# STAGE A -- self-protection (abort with a NAMED reason)
# =====================================================================
# STAGE 5 R4: the gate must never again grade a DIFFERENT mql5bot than the repo.
# gate_run16 imported an INSTALLED mql5bot on the Windows host, so R2's
# run_backtest changes were absent while R3's tools-file constant applied.
# Resolve mql5bot the SAME way every tool now does (via tools/_bootstrap) and
# assert its __file__ is inside the repo root; fail closed naming BOTH the repo
# root and where mql5bot actually came from. The raw JSON (recorded as evidence)
# states the resolved path + version, so every run names the code it graded.
$prov = Invoke-Decide @("provenance")
if (-not $prov.ok) {
    $reason = if ($prov.data) {
        "SELF_PROTECT_MQL5BOT_SOURCE: mql5bot resolved OUTSIDE the repo -- graded code is not shipped code. repo_root={0}; mql5bot_file={1}" -f $prov.data.repo_root, $prov.data.mql5bot_file
    } else { "SELF_PROTECT_MQL5BOT_SOURCE: mql5bot provenance could not be resolved" }
    Record-Stage 0 "self_protection" "FAIL" $reason @((New-Artifact $prov.raw)) | Out-Null
    Finish-Gate "self_protection"
}
Write-Host ("[owner-gate] mql5bot resolved IN-REPO: {0} (v{1})" -f $prov.data.mql5bot_file, $prov.data.mql5bot_version) -ForegroundColor Green
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
# STAGE 5 R4: name the code the gate is grading, in the verdict itself.
$spPass = "{0}, mql5bot IN-REPO ({1} v{2})" -f $spPass, $prov.data.mql5bot_file, $prov.data.mql5bot_version
if ($spNotes) { $spPass = "{0}. NOTE: {1}" -f $spPass, $spNotes }
Record-Stage 0 "self_protection" "PASS" $spPass @((New-Artifact $sp.raw), (New-Artifact $prov.raw)) | Out-Null

# =====================================================================
# STAGE 1 -- strict compile (decision from the LOG, not the exit code)
# =====================================================================
Enter-Stage 1 "strict_compile"
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
Enter-Stage 2 "dsl_parity"
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
Enter-Stage 3 "broker_parity"
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
Enter-Stage 4 "fixture_import"
$stage4ok = $true
$stage4art = New-Object System.Collections.ArrayList
# SYMBOL NAMES (R7, gate_run9): both golds are EURUSD fixtures. A custom
# symbol is Forex by default, and in Forex calc mode MT5 DERIVES the base and
# profit currencies from the first/second three-character chunks of the NAME
# (MQL5 book, "Custom symbol properties"): "GOLD1_EURUSD" -> base "GOL",
# profit "D1_", which broke verify_properties even though CustomSymbolSetString
# returned ok. The names are therefore the documented XXXYYY+suffix Forex form
# so MT5's own inference yields EUR/USD: "EURUSD.G1" -> base "EUR", profit
# "USD". The ".G1"/".G2" suffix keeps each unique and non-colliding with the
# broker's own "EURUSD". See docs/DECISIONS.md 2026-09-19 (R7).
$golds = @(
    @{ name = "EURUSD.G1"; fixture = "artifacts\gold\gold_fixture.csv";   manifest = "artifacts\gold\manifest.json" },
    @{ name = "EURUSD.G2"; fixture = "artifacts\gold_2\gold2_fixture.csv"; manifest = "artifacts\gold_2\manifest.json" }
)
$filesImport = Join-Path $DataFolder "MQL5\Files\Mql5Bot\gold_import"
$importOut = Join-Path $DataFolder "MQL5\Files\Mql5Bot\gold_import_out"
$presetsDir = Join-Path $DataFolder "MQL5\Presets"
foreach ($g in $golds) {
    New-Item -ItemType Directory -Force -Path $filesImport | Out-Null
    if (Test-Path -LiteralPath $importOut) { Remove-Item -LiteralPath $importOut -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $importOut | Out-Null
    New-Item -ItemType Directory -Force -Path $presetsDir | Out-Null
    Copy-Item -LiteralPath (Join-Path $RepoRoot $g.fixture) -Destination (Join-Path $filesImport "gold_fixture.csv") -Force
    Copy-Item -LiteralPath (Join-Path $RepoRoot $g.manifest) -Destination (Join-Path $filesImport "manifest.json") -Force
    if (Test-Path -LiteralPath $SymbolSpecExport) {
        New-Item -ItemType Directory -Force -Path (Join-Path $DataFolder "MQL5\Files\Mql5Bot\broker_exports") | Out-Null
        Copy-Item -LiteralPath $SymbolSpecExport -Destination (Join-Path $DataFolder "MQL5\Files\Mql5Bot\broker_exports\EURUSD.json") -Force
    }
    # The gate tells the importer WHICH gold it is and EXACTLY where to write
    # its JSON via a *.set preset -- never the script's compiled-in default
    # (that default is EURUSD.G1 and would collide across the two golds and
    # write to a path the gate is not watching). $outRel is the ONE path the
    # importer writes and the gate reads back.
    $outRel = "Mql5Bot\gold_import_out\" + $g.name + ".json"
    $setName = "mql5bot_import_" + $g.name + ".set"
    # R4 ROOT CAUSE (gate_run6): inside a PowerShell @() literal the COMMA
    # operator binds TIGHTER than '+', so `"InpSymbolName=" + $g.name,`
    # contributed TWO array elements -- the staged .set carried
    # "InpSymbolName=" (EMPTY) with GOLD1_EURUSD on the FOLLOWING line, and
    # likewise InpOutFile: exactly the two fixture-derived entries broke
    # while the five literals were fine, and the importer refused at
    # name_check with a blank symbol. Every element is now ONE interpolated
    # string; never use bare '+' concatenation inside an @() literal.
    $setLines = @(
        "InpFixtureCsv=Mql5Bot\gold_import\gold_fixture.csv",
        "InpManifest=Mql5Bot\gold_import\manifest.json",
        "InpSymbolSpec=Mql5Bot\broker_exports\EURUSD.json",
        "InpSymbolName=$($g.name)",
        "InpSymbolGroup=Mql5Bot\gold",
        "InpOutDir=Mql5Bot\gold_import_out",
        "InpOutFile=$outRel"
    )
    # PARAMETER DELIVERY (verified against the MT5 "Configuration at Startup"
    # help, terminal/help/start_advanced/start): [StartUp] ScriptParameters is
    # a bare FILE NAME resolved in MQL5\Presets of the platform data directory
    # ("The file must be located in the folder MQL5\presets") -- a .set staged
    # anywhere else is IGNORED and the script runs with its compiled-in
    # DEFAULTS, writing to its default path: the exact "terminal ran but no
    # JSON at the gate's path" symptom. The docs leave the file ENCODING
    # unstated; the terminal itself saves .set files as UTF-16LE, so stage in
    # that encoding (the one format the terminal provably reads back).
    [IO.File]::WriteAllText((Join-Path $presetsDir $setName), (($setLines -join "`r`n") + "`r`n"), [Text.Encoding]::Unicode)
    # archive the EXACT params the gate passed as evidence (byte copy of the
    # staged preset, so the artifact sha256 pins what the terminal was given)
    $setStaged = Join-Path $presetsDir $setName
    $setEvidence = Join-Path $Evidence ("import_" + $g.name + ".set")
    Copy-Item -LiteralPath $setStaged -Destination $setEvidence -Force
    [void]$stage4art.Add((New-Artifact $setEvidence))
    # attach the DECODED preset (UTF-16LE -> readable text) so a wrong value
    # can be read straight from the evidence dir, not just the raw bytes
    $setDecoded = Join-Path $Evidence ("import_" + $g.name + "_preset_decoded.txt")
    [IO.File]::WriteAllText($setDecoded, [IO.File]::ReadAllText($setStaged, [Text.Encoding]::Unicode), [Text.Encoding]::ASCII)
    [void]$stage4art.Add((New-Artifact $setDecoded))

    # VALIDATE BEFORE LAUNCH, fail-closed: re-read the STAGED .set back from
    # MQL5\Presets, decode it, and let committed Python assert it carries
    # EXACTLY the intended key=value pairs -- exact key set, every value
    # non-empty and single-line, no stray key-less lines, key count matching
    # what MT5 will report. Any violation FAILs stage 4 immediately, naming
    # the offending key, BEFORE the terminal is ever launched: a malformed
    # preset must never again cost a terminal round-trip.
    $expectArgs = @()
    foreach ($sl in $setLines) { $expectArgs += @("--expect", $sl) }
    $pv = Invoke-Decide (@("validate-preset", $setStaged) + $expectArgs)
    if (-not $pv.ok) {
        $why = if ($pv.data -and $pv.data.reasons) { ($pv.data.reasons -join "; ") } else { "staged preset failed validation" }
        Record-Stage 4 "fixture_import" "FAIL" ("[preset_invalid] {0}: {1}" -f $g.name, $why) @($stage4art) | Out-Null
        Finish-Gate "fixture_import"
    }

    # NOTE: the importer refuses (creates nothing) unless the staged fixture
    # sha256 equals the manifest dataset_hash and the CustomRatesUpdate
    # round-trip re-derives that same hash. It writes its JSON to $outRel on
    # EVERY exit path, including every early refusal.
    $man = Get-Content -LiteralPath (Join-Path $RepoRoot $g.manifest) -Raw | ConvertFrom-Json
    $resultJson = Join-Path $DataFolder ("MQL5\Files\" + $outRel)
    $run = Invoke-TerminalScript "Mql5Bot\Mql5BotImportFixture" ("import_" + $g.name) $setName

    # Three cases, DISTINCT messages (decided in committed Python, never the
    # .ps1): (1) terminal never launched, (2) terminal ran but no JSON, (3)
    # JSON present -- refused (reason surfaced verbatim) or a faithful import.
    # Backstop: when no JSON appeared, grep the MT5 log for the importer's own
    # lines so the cause is in the evidence dir either way.
    $logExcerptPath = ""
    if ($run.launched -and -not (Test-Path -LiteralPath $resultJson)) {
        # parameter-delivery proof: a run whose .set was NOT delivered uses the
        # compiled-in defaults and writes to the importer's DEFAULT path, so
        # any stray JSON in the import-out dir is named evidence of that cause
        # (it is copied into evidence\ and listed at the TOP of the excerpt).
        $extra = New-Object System.Collections.ArrayList
        $strays = @(Get-ChildItem -LiteralPath $importOut -Filter "*.json" -ErrorAction SilentlyContinue)
        foreach ($s in $strays) {
            [void]$extra.Add(("stray import-out JSON (importer ran with NON-gate inputs?): " + $s.FullName))
            $strayCopy = Join-Path $Evidence ("import_" + $g.name + "_stray_" + $s.Name)
            Copy-Item -LiteralPath $s.FullName -Destination $strayCopy -Force
            [void]$stage4art.Add((New-Artifact $strayCopy))
        }
        $logArt = Save-ImporterLog $g.name $extra
        if ($logArt) { [void]$stage4art.Add($logArt); $logExcerptPath = $logArt.path }
        # surface the excerpt head INLINE: a stage-4 failure must be
        # diagnosable from the gate's own console output alone
        if ($logExcerptPath -and (Test-Path -LiteralPath $logExcerptPath)) {
            Write-Host ("[owner-gate] stage-4 log excerpt head ({0}):" -f (Split-Path -Leaf $logExcerptPath)) -ForegroundColor Yellow
            Get-Content -LiteralPath $logExcerptPath -TotalCount 10 -ErrorAction SilentlyContinue |
                ForEach-Object { Write-Host ("    | " + $_) -ForegroundColor Yellow }
        }
    }
    # attach the importer diagnostic to stage_4.json whenever it exists (pass,
    # fail, or refusal) -- before the pass/fail branch so it is never lost.
    # SANDBOX PATTERN (same as DslParityRunner): the importer wrote INSIDE
    # MQL5\Files; the gate copies that file into evidence\ and records the
    # sha256 BEFORE and AFTER the copy, attaching BOTH, so a mangled copy can
    # never masquerade as the importer's output.
    if (Test-Path -LiteralPath $resultJson) {
        $shaBefore = Get-Sha256 $resultJson
        $resCopy = Join-Path $Evidence ("import_" + $g.name + ".json")
        Copy-Item -LiteralPath $resultJson -Destination $resCopy -Force
        $shaAfter = Get-Sha256 $resCopy
        Write-Host ("[owner-gate] import JSON sha256 before copy {0} / after copy {1}" -f $shaBefore, $shaAfter)
        if ($shaBefore -ne $shaAfter) {
            Write-Host ("[owner-gate] WARNING: evidence copy of {0} differs from the MQL5\Files original" -f $resultJson) -ForegroundColor Yellow
        }
        [void]$stage4art.Add([ordered]@{ path = $resultJson; sha256 = $shaBefore })
        [void]$stage4art.Add((New-Artifact $resCopy))
    }
    # R5: --log-excerpt is appended ONLY when a path exists -- an empty
    # element in the Start-Process -ArgumentList crashed the whole gate
    # verdictless in gate_run7 (Invoke-Decide also passes "" safely now).
    $ocArgs = @("stage4-outcome",
        "--symbol", $g.name,
        "--launched", ($run.launched.ToString().ToLower()),
        "--result", $resultJson,
        "--manifest-hash", $man.dataset_hash)
    if ($logExcerptPath) { $ocArgs += @("--log-excerpt", $logExcerptPath) }
    $oc = Invoke-Decide $ocArgs
    if (-not $oc.ok) {
        $stage4ok = $false
        $msg = if ($oc.data -and $oc.data.message) { $oc.data.message } else { ("{0}: stage-4 import failed" -f $g.name) }
        $case = if ($oc.data -and $oc.data.case) { $oc.data.case } else { "unknown" }
        Record-Stage 4 "fixture_import" "FAIL" ("[{0}] {1}" -f $case, $msg) @($stage4art) | Out-Null
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
Enter-Stage 5 "tester_legs"
$runBacktest = Join-Path $PSScriptRoot "run_mt5_backtest.py"
$legs = @(
    @{ gold = "gold1"; model = "m1_ohlc";    m = 1 },
    @{ gold = "gold1"; model = "every_tick"; m = 0 },
    @{ gold = "gold1"; model = "real_ticks"; m = 3 },
    @{ gold = "gold2"; model = "m1_ohlc";    m = 1 },
    @{ gold = "gold2"; model = "every_tick"; m = 0 },
    @{ gold = "gold2"; model = "real_ticks"; m = 3 }
)
# per-gold identity: the custom-symbol NAME the gate assigned (stage 4) and the
# committed manifest + fixture the tester period/timeframe are DERIVED from.
$goldMeta = @{
    gold1 = @{ symbol = "EURUSD.G1"; manifest = "artifacts\gold\manifest.json";   fixture = "artifacts\gold\gold_fixture.csv" }
    gold2 = @{ symbol = "EURUSD.G2"; manifest = "artifacts\gold_2\manifest.json"; fixture = "artifacts\gold_2\gold2_fixture.csv" }
}
$legArt = New-Object System.Collections.ArrayList
$legReasons = New-Object System.Collections.ArrayList
$legOk = $true
$terminalDir = Split-Path -Parent $TerminalPath
$testerOut = Join-Path $Evidence "tester"

# NEVER GUESS A TESTER SETTING: derive the timeframe (from the manifest) and
# the period (from the fixture's first/last bar) once per gold. If any input
# cannot be derived, FAIL the stage naming that input -- do not run with an
# invented value.
$derived = @{}
foreach ($gk in @("gold1", "gold2")) {
    $meta = $goldMeta[$gk]
    $ti = Invoke-Decide @("tester-inputs",
        "--manifest", (Join-Path $RepoRoot $meta.manifest),
        "--fixture", (Join-Path $RepoRoot $meta.fixture))
    [void]$legArt.Add((New-Artifact $ti.raw))
    if (-not $ti.ok) {
        $why = if ($ti.data -and $ti.data.reasons) { ($ti.data.reasons -join "; ") } else { "tester inputs underivable" }
        $miss = if ($ti.data) { $ti.data.missing } else { "unknown" }
        Record-Stage 5 "tester_legs" "FAIL" ("[input_underivable] {0} ({1}): {2}" -f $gk, $miss, $why) @($legArt) | Out-Null
        Finish-Gate "tester_legs"
    }
    $derived[$gk] = $ti.data
}

foreach ($leg in $legs) {
    $gk = $leg.gold
    $meta = $goldMeta[$gk]
    $d = $derived[$gk]
    $sym = $meta.symbol
    $tf = $d.timeframe
    $from = $d.date_from
    $to = $d.date_to
    $reportName = "{0}_{1}" -f $gk, $leg.model
    $legTag = $reportName

    # (i) ALWAYS-present intended tester .ini (pure Python, no terminal): the
    # exact [Tester]/[TesterInputs] the gate intends, so a leg that never
    # produces a report still attaches the config it was asked to run.
    $iniEvidence = Join-Path $Evidence ("tester_" + $legTag + ".ini")
    $genArgs = @($runBacktest, "generate-ini", "--symbol", $sym,
        "--timeframe", $tf, "--model", ([string]$leg.m), "--from", $from,
        "--to", $to, "--report", $reportName, "--output", $iniEvidence)
    $gp = Start-Process -FilePath $Python -ArgumentList (Get-ProcArgs $genArgs) `
        -Wait -PassThru -NoNewWindow
    if (Test-Path -LiteralPath $iniEvidence) { [void]$legArt.Add((New-Artifact $iniEvidence)) }
    if ($gp.ExitCode -ne 0) {
        $legOk = $false
        [void]$legReasons.Add(("{0}: could not render the intended tester .ini (generate-ini exit {1})" -f $legTag, $gp.ExitCode))
    }

    # (ii) the command line EXACTLY as invoked, quoted the way it is passed --
    # so a re-split (the STAGE 5 R1 defect) is visible straight from evidence.
    $runArgs = @("run", "--terminal-dir", $terminalDir, "--data-folder", $DataFolder,
        "--symbol", $sym, "--timeframe", $tf, "--model", ([string]$leg.m),
        "--from", $from, "--to", $to, "--report", $reportName, "--out-dir", $testerOut)
    $cmdArgv = @($Python, $runBacktest) + $runArgs
    $cmdlinePath = Join-Path $Evidence ("tester_" + $legTag + "_cmdline.txt")
    [IO.File]::WriteAllText($cmdlinePath, ((Get-ProcArgs $cmdArgv) -join " ") + "`r`n", [Text.Encoding]::ASCII)
    [void]$legArt.Add((New-Artifact $cmdlinePath))

    # (iii) run the tester leg with stdout + stderr captured to files (attached
    # on pass OR fail -- a failing leg with an empty artifacts array is not
    # diagnosable, the STAGE 5 R1 rule).
    $stdoutPath = Join-Path $Evidence ("tester_" + $legTag + "_stdout.txt")
    $stderrPath = Join-Path $Evidence ("tester_" + $legTag + "_stderr.txt")
    # DEFECT 2: mark the leg's window so a failing leg can attach the unfiltered
    # tail of exactly the tester logs written while THIS leg ran.
    $legStart = (Get-Date).AddSeconds(-2)
    $p = Start-Process -FilePath $Python -ArgumentList (Get-ProcArgs (@($runBacktest) + $runArgs)) `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath `
        -Wait -PassThru -NoNewWindow
    if (Test-Path -LiteralPath $stdoutPath) { [void]$legArt.Add((New-Artifact $stdoutPath)) }
    if (Test-Path -LiteralPath $stderrPath) { [void]$legArt.Add((New-Artifact $stderrPath)) }

    # (iv) the tester-journal excerpt (always attached; empty = "nothing found")
    $journalArt = Save-TesterLog $legTag $reportName $sym
    if ($journalArt) { [void]$legArt.Add($journalArt) }

    # (v) the run-dir artifacts (tool tester.ini, raw .htm, report.json sidecar)
    $runRoot = Join-Path $testerOut "runs"
    $latest = Get-ChildItem -LiteralPath $runRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like ($reportName + "_*") } |
        Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    $reportJson = ""
    if ($latest) {
        Get-ChildItem -LiteralPath $latest.FullName -File | ForEach-Object {
            [void]$legArt.Add((New-Artifact $_.FullName))
            if ($_.Name -eq "report.json") { $reportJson = $_.FullName }
        }
    }

    if ($p.ExitCode -ne 0) {
        $legOk = $false
        # DEFECT 2: attach the unfiltered tail -- the exit-code failure lines
        # ("no history", init/file errors) are what explain this, not the
        # modelling-quality excerpt.
        $tailArt = Save-TesterFailLog $legTag $legStart
        if ($tailArt) { [void]$legArt.Add($tailArt) }
        [void]$legReasons.Add(("{0}: tester leg exit {1} (see tester_{0}_cmdline.txt + _stderr.txt + _journal.txt + _journal_tail.txt)" -f $legTag, $p.ExitCode))
        continue
    }
    if (-not $reportJson) {
        $legOk = $false
        $tailArt = Save-TesterFailLog $legTag $legStart
        if ($tailArt) { [void]$legArt.Add($tailArt) }
        [void]$legReasons.Add(("{0}: tester leg exited 0 but produced no report.json sidecar (see tester_{0}_journal_tail.txt)" -f $legTag))
        continue
    }

    # (vi) read the ACTUAL model + real-tick coverage from THIS leg's report +
    # journal (never the requested model). A leg whose model cannot be
    # confirmed fails; a model that differs from the requested one is recorded.
    $le = Invoke-Decide @("stage5-leg", "--report-json", $reportJson,
        "--journal", $journalArt.path, "--requested-model", ([string]$leg.m),
        "--symbol", $sym, "--leg", $legTag)
    [void]$legArt.Add((New-Artifact $le.raw))
    if ($le.ok -and $le.data) {
        $am = if ($le.data.actual_model) { $le.data.actual_model.label } else { "?" }
        $cov = $le.data.coverage
        [void]$legReasons.Add(("{0}: actual model={1} (src {2}), real-tick coverage={3}" -f `
            $legTag, $am, $le.data.actual_model.source, $cov))
    } else {
        $legOk = $false
        $tailArt = Save-TesterFailLog $legTag $legStart
        if ($tailArt) { [void]$legArt.Add($tailArt) }
        $why = if ($le.data -and $le.data.reasons) { ($le.data.reasons -join "; ") } else { "actual model unreadable" }
        [void]$legReasons.Add(("{0}: {1} (see tester_{0}_journal_tail.txt)" -f $legTag, $why))
    }
}

# (vii) re-check the dataset hash AFTER the legs to prove the fixtures were not
# mutated by the run (the gate never lets a tester leg touch a frozen input).
foreach ($gk in @("gold1", "gold2")) {
    $meta = $goldMeta[$gk]
    $man = Get-Content -LiteralPath (Join-Path $RepoRoot $meta.manifest) -Raw | ConvertFrom-Json
    $dh = Invoke-Decide @("dataset-hash", (Join-Path $RepoRoot $meta.fixture))
    if (-not $dh.data -or ($dh.data.sha256 -ne $man.dataset_hash)) {
        $got = if ($dh.data) { $dh.data.sha256 } else { "(unreadable)" }
        $legOk = $false
        [void]$legReasons.Add(("{0}: POST-LEG dataset hash mutated: got {1} != manifest {2}" -f $gk, $got, $man.dataset_hash))
    } else {
        [void]$legReasons.Add(("{0}: post-leg dataset hash intact ({1})" -f $gk, $man.dataset_hash))
    }
}

if (-not $legOk) {
    Record-Stage 5 "tester_legs" "FAIL" (($legReasons -join "; ")) @($legArt) | Out-Null
    Finish-Gate "tester_legs"
}
Record-Stage 5 "tester_legs" "PASS" ("six tester legs; actual models + real-tick coverage read from report+journal; dataset hash intact after the legs. " + ($legReasons -join "; ")) @($legArt) | Out-Null

# =====================================================================
# STAGE 8 -- reconciliation (full bindings + 8a kill-switch, 8b restart,
#            8c retry/adoption/SlGuard, 8d NETTING and HEDGING) via the
#            evidence CONSUMER. A volume/risk divergence is EXPECTED for
#            the 4257f1e sizing fix: classify + record, never patch.
# =====================================================================
Enter-Stage 8 "reconciliation"
$evidencePkg = if ($env:MQL5BOT_EVIDENCE_DIR) { $env:MQL5BOT_EVIDENCE_DIR } else { Join-Path $RepoRoot "artifacts\owner_mt5_gate\evidence" }
$verifyOut = Join-Path $Evidence "reconciliation_verify.json"
$vp = Start-Process -FilePath $Python `
    -ArgumentList (Get-ProcArgs (@((Join-Path $PSScriptRoot "verify_owner_mt5_gate.py"), $evidencePkg, "--repo", $RepoRoot, "--out", $verifyOut))) `
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
Enter-Stage 9 "archive_manifest"
$archiveManifest = Join-Path $Evidence "archive_manifest.json"
$ap = Start-Process -FilePath $Python `
    -ArgumentList (Get-ProcArgs (@((Join-Path $PSScriptRoot "owner_evidence_bind.py"), "manifest", $Evidence, "--frozen", (Join-Path $RepoRoot "artifacts\owner_mt5_gate\frozen_inputs.json")))) `
    -RedirectStandardOutput $archiveManifest -Wait -PassThru -NoNewWindow
if ($ap.ExitCode -ne 0) {
    Record-Stage 9 "archive_manifest" "FAIL" ("owner_evidence_bind.py exit {0}" -f $ap.ExitCode) @() | Out-Null
    Finish-Gate "archive_manifest"
}
Record-Stage 9 "archive_manifest" "PASS" "evidence bound by owner_evidence_bind.py (no hand-typed hash)" @((New-Artifact $archiveManifest)) | Out-Null

# =====================================================================
# STAGE 10 -- certify_strategy.py records whatever state it assigns
# =====================================================================
Enter-Stage 10 "certify"
$certConfig = Join-Path $RepoRoot "artifacts\owner_mt5_gate\certify_config.json"
$certReport = Join-Path $Evidence "certification_report.md"
if (-not (Test-Path -LiteralPath $certConfig)) {
    Record-Stage 10 "certify" "SKIP" "no certify_config.json present; certification state unassigned" @() | Out-Null
    Finish-Gate "reconciliation"
}
$cp = Start-Process -FilePath $Python `
    -ArgumentList (Get-ProcArgs (@((Join-Path $PSScriptRoot "certify_strategy.py"), "--config", $certConfig, "--out", $certReport))) `
    -Wait -PassThru -NoNewWindow
$certStatus = if ($cp.ExitCode -eq 0) { "PASS" } else { "FAIL" }
Record-Stage 10 "certify" $certStatus ("certify_strategy.py exit {0} (state recorded as assigned)" -f $cp.ExitCode) @((New-Artifact $certReport)) | Out-Null
if ($certStatus -eq "FAIL") { Finish-Gate "certify" }

Finish-Gate "certified"
