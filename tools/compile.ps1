<#
.SYNOPSIS
  AEGIS compile round-trip: build the mql5bot EA with MetaEditor from the
  command line and produce a reproducible compile log.

  This implements canonical owner steps 1-2 (strict compile + compiler-
  log verification) of the TEN-step owner sequence in
  docs/MT5_ROUNDTRIP.md - the single source of truth for the owner
  protocol. The 0-error/0-warning count must be read from the produced
  log, and a SOFTWARE_FAIL here never upgrades any certification state.

.DESCRIPTION
  Phase-1 tool for the AEGIS research/performance mission (SPEC 14/17 DoD
  item 1: "MQL5 compiles 0 errors / 0 warnings (log attached)").

  Steps performed:
    1. Locate metaeditor64.exe (see -MetaEditorPath / env MQL5BOT_METAEDITOR).
    2. Resolve the MT5 data folder MetaEditor will compile against
       (see -DataFolder / env MQL5BOT_DATA_FOLDER).  Includes are resolved
       by MetaEditor inside that data folder's MQL5\Include tree, so the
       sources must be installed there first.
    3. Install (copy) the repo's mql5/ sources into <data>\MQL5\... unless
       -SkipInstall is given.
    4. Compile every *.mq5 under Experts\Mql5Bot and Scripts\Mql5Bot with
       metaeditor64.exe /compile:... /log:..., one invocation per file.
    5. Gate on REAL compiler output, never on assumptions:
         - the .ex5 must exist AND be newer than the compile start time
           (an outdated .ex5 left over from an earlier successful build is
           NOT proof of success), and
         - the captured compiler log is kept verbatim.
       English severity tokens (error/warning) are counted when present;
       logs from non-English MetaEditor builds simply carry no such tokens,
       so the .ex5 freshness check is authoritative, and the raw log is
       always preserved for human review.  This caveat is documented in
       tools/README.md.
    6. Write one reproducible combined log to logs\compile-<UTC stamp>.log
       (full command lines, versions, per-file verdicts, verbatim compiler
       logs, SHA-256 of produced .ex5 files).  logs/ is gitignored.

  Exit codes:
    0  PASS -- every file compiled, 0 errors; warnings=0 (or <N> when the
       compiler log shows warnings and -Strict was NOT passed)
    2  FAIL -- compile errors detected (or .ex5 not refreshed)
    3  FAIL -- -Strict given and the compiler log contains warning tokens
    1  FAIL -- metaeditor64.exe not found
    4  FAIL -- data folder not found / not usable
    5  FAIL -- script error (exception)

  Examples (run from the repo root; Windows PowerShell 5.1+):
    powershell -ExecutionPolicy Bypass -File tools\compile.ps1
    powershell -ExecutionPolicy Bypass -File tools\compile.ps1 -Strict
    powershell -ExecutionPolicy Bypass -File tools\compile.ps1 `
        -MetaEditorPath "D:\MT5\metaeditor64.exe" `
        -DataFolder "D:\MT5-portable-tester" `
        -Strict

.NOTES
  Written for the AEGIS mission (arena/01a06cdc-mql5bot).  Never claim a
  green compile from this sandbox: MetaEditor is Windows-only and absent
  here.  The OWNER (or a Windows runner) executes this script and pastes
  the printed RESULT + log path back into the session.
#>
[CmdletBinding()]
param(
    # Full path to metaeditor64.exe. When empty: env MQL5BOT_METAEDITOR,
    # then Program Files\MetaTrader*\metaeditor64.exe, then Start-menu
    # shortcuts, then PATH, then registry-known portable roots.
    [string]$MetaEditorPath = "",

    # MT5 data folder (folder that contains MQL5\). When empty: env
    # MQL5BOT_DATA_FOLDER, then registry DataPath (newest), then portable
    # roots from origin.txt, then newest %APPDATA%...\Terminal\<hash>.
    [string]$DataFolder = "",

    # Fail the run when the compiler log shows any warning token.
    [switch]$Strict,

    # Do not copy repo mql5/ sources into the data folder (compile what is
    # already installed there).
    [switch]$SkipInstall,

    # Repo root; auto-detected from this script's location when omitted.
    [string]$RepoRoot = "",

    # Directory for the combined reproducible log; default <RepoRoot>\logs.
    [string]$OutDir = ""
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$script:exitCode = 0

function Write-Step($msg) { Write-Host "[compile] $msg" }
function Write-Fail($msg) { Write-Host "[compile] FAIL: $msg" -ForegroundColor Red }

#------------------------------------------------------------------ paths
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
if (-not $OutDir)  { $OutDir = Join-Path $RepoRoot "logs" }
[IO.Directory]::CreateDirectory($OutDir) | Out-Null

$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmss")
$combinedLog = Join-Path $OutDir "compile-$stamp.log"
$combined = New-Object System.Collections.Generic.List[string]

function Add-Log($line) {
    $combined.Add($line)
    Write-Host $line
}

try {
    Add-Log "# AEGIS compile run $stamp (UTC)"
    Add-Log "# host: $env:COMPUTERNAME  user: $env:USERNAME"
    Add-Log "# script: $($MyInvocation.MyCommand.Path)"
    Add-Log "# repo root: $RepoRoot"
    Add-Log "# strict: $([bool]$Strict)   skipInstall: $([bool]$SkipInstall)"
    Add-Log "# ps: $($PSVersionTable.PSVersion)"

    #------------------------------------ 0. known terminal roots (registry
    # DataPath keys + portable roots from origin.txt).  Used both to locate
    # metaeditor64.exe (portable installs keep it in the terminal root) and
    # to resolve the data folder both tools compile against.
    $roots = New-Object System.Collections.Generic.List[string]
    try {
        Get-ChildItem "HKCU:\Software\MetaQuotes\Terminal" -ErrorAction SilentlyContinue |
            ForEach-Object {
                $dp = (Get-ItemProperty -Path $_.PSPath -Name DataPath -ErrorAction SilentlyContinue).DataPath
                if ($dp) { $roots.Add([string]$dp) }
            }
    } catch { }
    $origin = Join-Path $env:APPDATA "MetaQuotes\Terminal\origin.txt"
    if (Test-Path -LiteralPath $origin) {
        Get-Content -LiteralPath $origin -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_ -match "^\S+\s+(.+)$") { $roots.Add($Matches[1].Trim()) }
        }
    }
    $roots = @($roots | Select-Object -Unique | Where-Object { Test-Path -LiteralPath $_ })

    #------------------------------------------------------ 1. metaeditor
    if (-not $MetaEditorPath -and $env:MQL5BOT_METAEDITOR) {
        $MetaEditorPath = $env:MQL5BOT_METAEDITOR
    }
    if ($MetaEditorPath -and -not (Test-Path -LiteralPath $MetaEditorPath)) {
        Write-Fail "MetaEditorPath not found: $MetaEditorPath"
        exit 1
    }
    if (-not $MetaEditorPath) {
        $candidates = New-Object System.Collections.Generic.List[string]
        # exe next to each known terminal root (portable installs)
        foreach ($root in $roots) {
            $p = Join-Path $root "metaeditor64.exe"
            if (Test-Path -LiteralPath $p) { $candidates.Add($p) }
        }
        foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
            if (-not $base -or -not (Test-Path -LiteralPath $base)) { continue }
            Get-ChildItem -LiteralPath $base -Directory -Filter "MetaTrader*" -ErrorAction SilentlyContinue |
                ForEach-Object {
                    $p = Join-Path $_.FullName "metaeditor64.exe"
                    if (Test-Path -LiteralPath $p) { $candidates.Add($p) }
                }
        }
        # Start-menu shortcuts
        try {
            $shell = New-Object -ComObject WScript.Shell
            Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs" -Recurse `
                    -Filter "*.lnk" -ErrorAction SilentlyContinue | ForEach-Object {
                try {
                    $t = $shell.CreateShortcut($_.FullName).TargetPath
                    if ($t -and $t -match "metaeditor64\.exe$" -and (Test-Path -LiteralPath $t)) {
                        $candidates.Add($t)
                    }
                } catch { }
            }
        } catch { }
        $cmd = Get-Command metaeditor64.exe -ErrorAction SilentlyContinue
        if ($cmd) { $candidates.Add($cmd.Source) }
        $MetaEditorPath = $candidates | Select-Object -Unique | Where-Object { Test-Path -LiteralPath $_ } |
            Select-Object -First 1
    }
    if (-not $MetaEditorPath) {
        Write-Fail "metaeditor64.exe not found. Pass -MetaEditorPath or set MQL5BOT_METAEDITOR."
        Add-Log "[compile] RESULT: FAIL -- metaeditor64.exe not found (exit 1)"
        exit 1
    }
    $meVersion = (Get-Item -LiteralPath $MetaEditorPath).VersionInfo
    Add-Log "# metaeditor: $MetaEditorPath"
    Add-Log "# metaeditor version: $($meVersion.FileVersion)"

    #----------------------------------------------------- 2. data folder
    if (-not $DataFolder -and $env:MQL5BOT_DATA_FOLDER) {
        $DataFolder = $env:MQL5BOT_DATA_FOLDER
    }
    if (-not $DataFolder) {
        $dPaths = New-Object System.Collections.Generic.List[string]
        foreach ($root in $roots) {
            if (Test-Path -LiteralPath (Join-Path $root "MQL5")) { $dPaths.Add($root) }
        }
        # newest %APPDATA%...\Terminal\<hash> containing MQL5
        $termBase = Join-Path $env:APPDATA "MetaQuotes\Terminal"
        if (Test-Path -LiteralPath $termBase) {
            Get-ChildItem -LiteralPath $termBase -Directory -ErrorAction SilentlyContinue |
                Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "MQL5") } |
                Sort-Object LastWriteTimeUtc -Descending | ForEach-Object { $dPaths.Add($_.FullName) }
        }
        $DataFolder = $dPaths | Select-Object -Unique |
            Where-Object { Test-Path -LiteralPath (Join-Path $_ "MQL5") } | Select-Object -First 1
    }
    if (-not $DataFolder -or -not (Test-Path -LiteralPath $DataFolder)) {
        Write-Fail "MT5 data folder not found. Pass -DataFolder or set MQL5BOT_DATA_FOLDER."
        Add-Log "[compile] RESULT: FAIL -- data folder not found (exit 4)"
        exit 4
    }
    $mql5Dir = Join-Path $DataFolder "MQL5"
    [IO.Directory]::CreateDirectory($mql5Dir) | Out-Null
    Add-Log "# data folder: $DataFolder"

    #-------------------------------------------- 3. install repo sources
    $pairs = @(
        @("Include\Mql5Bot",  "Include\Mql5Bot"),   # repo-relative, data-relative
        @("Experts\Mql5Bot",  "Experts\Mql5Bot"),
        @("Scripts\Mql5Bot",  "Scripts\Mql5Bot"),
        @("Presets\Mql5Bot",  "Presets\Mql5Bot")
    )
    if (-not $SkipInstall) {
        foreach ($pair in $pairs) {
            $src = Join-Path (Join-Path $RepoRoot "mql5") $pair[0]
            $dst = Join-Path $mql5Dir $pair[1]
            if (-not (Test-Path -LiteralPath $src)) { continue }
            [IO.Directory]::CreateDirectory($dst) | Out-Null
            Get-ChildItem -LiteralPath $src -File | ForEach-Object {
                Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $dst $_.Name) -Force
                Add-Log "# installed: $($pair[1])\$($_.Name)"
            }
        }
    }

    #------------------------------------------------ 4+5. compile each
    $targets = New-Object System.Collections.Generic.List[string]
    foreach ($sub in @("Experts\Mql5Bot", "Scripts\Mql5Bot")) {
        $dir = Join-Path $mql5Dir $sub
        if (Test-Path -LiteralPath $dir) {
            Get-ChildItem -LiteralPath $dir -Filter "*.mq5" -File |
                ForEach-Object { $targets.Add($_.FullName) }
        }
    }
    if ($targets.Count -eq 0) {
        Write-Fail "no *.mq5 under $mql5Dir\Experts\Mql5Bot or Scripts\Mql5Bot"
        Add-Log "[compile] RESULT: FAIL -- nothing to compile (exit 4)"
        exit 4
    }

    $failures = @()
    $strictWarnings = @()
    $compiled = @()
    # per-file compiler logs live in %TEMP% (never pollute the repo); the
    # combined reproducible log is the artifact that gets kept in logs/.
    $perDir = Join-Path ([IO.Path]::GetTempPath()) "aegis-compile-$stamp"
    [IO.Directory]::CreateDirectory($perDir) | Out-Null
    foreach ($target in $targets) {
        $name = [IO.Path]::GetFileName($target)
        $perLog = Join-Path $perDir "compile-$name.log"
        $startUtc = [DateTime]::UtcNow
        Add-Log ""
        Add-Log "# compiling: $target"
        try {
            $argLine = '/compile:"{0}" /log:"{1}"' -f $target, $perLog
            $proc = Start-Process -FilePath $MetaEditorPath -ArgumentList $argLine `
                -Wait -PassThru -WindowStyle Hidden
        } catch {
            Write-Fail "MetaEditor launch failed for $name : $($_.Exception.Message)"
            $failures += $name
            continue
        }
        $logText = ""
        if (Test-Path -LiteralPath $perLog) {
            # BOM-aware decode (MetaEditor logs may be UTF-8 or UTF-16)
            $logText = [IO.File]::ReadAllText($perLog)
        }
        # authoritative gate: freshly written .ex5
        $ex5 = [IO.Path]::ChangeExtension($target, ".ex5")
        $fresh = $false
        if (Test-Path -LiteralPath $ex5) {
            $ex5Time = (Get-Item -LiteralPath $ex5).LastWriteTimeUtc
            if ($ex5Time -ge $startUtc.AddSeconds(-2)) { $fresh = $true }
        }
        # severity tokens (English builds; locale caveat documented)
        $errTok = @([regex]::Matches($logText, '(?im)^.*\berror\b.*$')).Count
        $warnTok = @([regex]::Matches($logText, '(?im)^.*\bwarning\b.*$')).Count
        $sumErr = 0; $sumWarn = 0
        if ($logText -match '(?i)(\d+)\s+errors?') { $sumErr = [int]$Matches[1] }
        if ($logText -match '(?i)(\d+)\s+warnings?') { $sumWarn = [int]$Matches[1] }
        $ok = $fresh -and $errTok -eq 0
        if ($ok) {
            $hash = if (Test-Path -LiteralPath $ex5) {
                (Get-FileHash -LiteralPath $ex5 -Algorithm SHA256).Hash
            } else { "n/a" }
            $compiled += "$name  ex5=$hash"
            $verdict = "PASS"
            if ($warnTok -gt 0 -or $sumWarn -gt 0) {
                $verdict = "PASS(WARNINGS=$([Math]::Max($warnTok, $sumWarn)))"
                if ($Strict) { $strictWarnings += $name }
            }
            Add-Log "[compile] $name : $verdict (exit $($proc.ExitCode), ex5 fresh=$fresh)"
        } else {
            $verdict = "FAIL"
            $failures += $name
            Add-Log "[compile] $name : FAIL (exit $($proc.ExitCode), ex5 fresh=$fresh, errorTokens=$errTok)"
        }
        Add-Log "----- compiler log ($name) -----"
        if ($logText) {
            $logText -split "`r?`n" | ForEach-Object { Add-Log $_ }
        } else {
            Add-Log "(no log captured at $perLog)"
        }
    }

    #------------------------------------------------- 6. combined log
    Add-Log ""
    Add-Log "===== summary ====="
    if ($failures.Count -gt 0) {
        Add-Log "[compile] RESULT: FAIL -- errors in: $($failures -join ', ') (exit 2)"
        $script:exitCode = 2
    } elseif ($Strict -and $strictWarnings.Count -gt 0) {
        Add-Log "[compile] RESULT: FAIL (strict) -- warnings in: $($strictWarnings -join ', ') (exit 3)"
        $script:exitCode = 3
    } else {
        Add-Log "[compile] RESULT: PASS -- $($compiled.Count) file(s) compiled clean"
        Add-Log "  $($compiled -join "`n  ")"
        $script:exitCode = 0
    }
    Add-Log "# combined log: $combinedLog"
    $combined | Out-File -LiteralPath $combinedLog -Encoding UTF8
    Write-Host "[compile] combined log written to: $combinedLog"
    exit $script:exitCode
} catch {
    Write-Fail "unexpected error: $($_.Exception.ToString())"
    Add-Log "[compile] RESULT: FAIL -- exception (exit 5)"
    try { $combined | Out-File -LiteralPath $combinedLog -Encoding UTF8 } catch { }
    exit 5
}
