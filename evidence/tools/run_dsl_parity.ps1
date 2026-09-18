<#
.SYNOPSIS
  AEGIS DSL cross-engine parity leg (owner / Windows runner).

.DESCRIPTION
  One-shot, deterministic driver for the MQL5 side of the DSL parity
  contract (mission 12/13):

    1. Verify + copy every committed fixture from artifacts\dsl_parity\
       (all 14 manifest fixtures AND the tampered_bundle negative) into
       <data>\MQL5\Files\Mql5Bot\dsl_parity\<fixture>\ and write the
       batch list Mql5Bot\dsl_parity\fixtures.txt (LF, sorted).
       Every copied ohlc.csv/bundle.json is sha256-checked against
       manifest.json BEFORE the run: a CRLF-mangled or drifted checkout
       stops here instead of producing a garbage parity verdict.
    2. Launch terminal64.exe /config:<ini> with
       [StartUp] Script=Mql5Bot\DslParityRunner + ShutdownTerminal=1
       and wait for the terminal to exit.  The runner itself reads ONLY
       the copied fixture files (no CopyRates, no live history).
    3. Copy MQL5\Files\Mql5Bot\dsl_parity_out\*.json back into
       evidence\dsl_parity\<stamp>\, write a sha256 manifest over the
       consumed inputs + produced outputs, and run
       tools\compare_dsl_parity.py.  Exit code = comparator verdict
       (0 only when 14/14 EXACT and the tampered bundle was REFUSED).

  Prerequisites: DslParityRunner.ex5 must already be compiled into
  <data>\MQL5\Scripts\Mql5Bot\ (tools\compile.ps1 -Strict).  This
  script never fabricates a result; without a real terminal run there
  is no verdict.

.PARAMETER TerminalPath
  Full path to terminal64.exe.  Fallback: env MQL5BOT_TERMINAL, then
  terminal64.exe next to the data folder.

.PARAMETER DataFolder
  MT5 data folder (the folder that contains MQL5\).  Fallback: env
  MQL5BOT_DATA_FOLDER.

.PARAMETER Portable
  Pass /portable to the terminal (portable installations where the
  data folder IS the terminal folder).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\run_dsl_parity.ps1 `
      -TerminalPath D:\MT5\terminal64.exe -DataFolder D:\MT5 -Portable
#>
[CmdletBinding()]
param(
    [string]$TerminalPath = "",
    [string]$DataFolder = "",
    [switch]$Portable,
    [int]$TimeoutSec = 600
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Write-Fail([string]$msg) {
    Write-Host "[dsl-parity] FAIL: $msg" -ForegroundColor Red
    exit 2
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$gold = Join-Path $repoRoot "artifacts\dsl_parity"
$manifestPath = Join-Path $gold "manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath)) {
    Write-Fail "manifest not found: $manifestPath"
}

# ---- resolve terminal + data folder (never guessed silently) ---------
if (-not $DataFolder -and $env:MQL5BOT_DATA_FOLDER) {
    $DataFolder = $env:MQL5BOT_DATA_FOLDER
}
if (-not $DataFolder) {
    Write-Fail "MT5 data folder unknown. Pass -DataFolder or set MQL5BOT_DATA_FOLDER."
}
if (-not (Test-Path -LiteralPath (Join-Path $DataFolder "MQL5"))) {
    Write-Fail "data folder has no MQL5\ subfolder: $DataFolder"
}
if (-not $TerminalPath -and $env:MQL5BOT_TERMINAL) {
    $TerminalPath = $env:MQL5BOT_TERMINAL
}
if (-not $TerminalPath) {
    $cand = Join-Path $DataFolder "terminal64.exe"
    if (Test-Path -LiteralPath $cand) { $TerminalPath = $cand }
}
if (-not $TerminalPath -or -not (Test-Path -LiteralPath $TerminalPath)) {
    Write-Fail "terminal64.exe not found. Pass -TerminalPath or set MQL5BOT_TERMINAL."
}

$ex5 = Join-Path $DataFolder "MQL5\Scripts\Mql5Bot\DslParityRunner.ex5"
if (-not (Test-Path -LiteralPath $ex5)) {
    Write-Fail "DslParityRunner.ex5 not compiled at $ex5 (run tools\compile.ps1 -Strict first)"
}

# ---- 1. verify + copy fixtures, write the batch list -----------------
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$names = @($manifest.fixtures.PSObject.Properties.Name | Sort-Object)
$filesRoot = Join-Path $DataFolder "MQL5\Files\Mql5Bot\dsl_parity"
$outRoot = Join-Path $DataFolder "MQL5\Files\Mql5Bot\dsl_parity_out"

foreach ($name in $names) {
    $srcDir = Join-Path $gold $name
    $dstDir = Join-Path $filesRoot $name
    New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
    foreach ($f in @("bundle.json", "ohlc.csv")) {
        $src = Join-Path $srcDir $f
        $pinned = $manifest.fixtures.$name.files.$f
        $got = (Get-FileHash -LiteralPath $src -Algorithm SHA256).Hash.ToLower()
        if ($got -ne $pinned) {
            Write-Fail ("checkout drift: {0}/{1} sha256 {2} != manifest pin {3} " -f $name, $f, $got, $pinned) `
                + "(CRLF-mangled clone? re-clone with the repo .gitattributes)"
        }
        Copy-Item -LiteralPath $src -Destination (Join-Path $dstDir $f) -Force
    }
}
# tampered negative (deliberately outside the manifest)
$tampered = Join-Path $gold "tampered_bundle"
if (-not (Test-Path -LiteralPath (Join-Path $tampered "bundle.json"))) {
    Write-Fail "tampered_bundle fixture missing from $gold"
}
$dstDir = Join-Path $filesRoot "tampered_bundle"
New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
Copy-Item -LiteralPath (Join-Path $tampered "bundle.json") -Destination (Join-Path $dstDir "bundle.json") -Force
Copy-Item -LiteralPath (Join-Path $tampered "ohlc.csv") -Destination (Join-Path $dstDir "ohlc.csv") -Force

$runList = @($names) + @("tampered_bundle")
$listPath = Join-Path $filesRoot "fixtures.txt"
[IO.File]::WriteAllText($listPath, (($runList -join "`n") + "`n"))
Write-Host ("[dsl-parity] staged {0} fixtures (incl. tampered_bundle) -> {1}" -f $runList.Count, $filesRoot)

# clean output dir so stale traces can never leak into the verdict
if (Test-Path -LiteralPath $outRoot) {
    Remove-Item -LiteralPath $outRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $outRoot | Out-Null

# ---- 2. launch the terminal with the startup script ------------------
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$evidence = Join-Path $repoRoot ("evidence\dsl_parity\" + $stamp)
New-Item -ItemType Directory -Force -Path $evidence | Out-Null

$iniPath = Join-Path $evidence "dsl_parity.ini"
$ini = @(
    "[StartUp]",
    "Script=Mql5Bot\DslParityRunner",
    "ShutdownTerminal=1"
) -join "`r`n"
[IO.File]::WriteAllText($iniPath, $ini + "`r`n", [Text.Encoding]::ASCII)

$argList = @("/config:$iniPath")
if ($Portable) { $argList += "/portable" }
Write-Host "[dsl-parity] launching: $TerminalPath $($argList -join ' ')"
$proc = Start-Process -FilePath $TerminalPath -ArgumentList $argList -PassThru
if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
    $proc.Kill()
    Write-Fail "terminal did not exit within $TimeoutSec s (ShutdownTerminal missing?)"
}
Write-Host ("[dsl-parity] terminal exited (code {0})" -f $proc.ExitCode)

# ---- 3. collect outputs, sha256 manifest, comparator verdict ---------
$outFiles = @(Get-ChildItem -LiteralPath $outRoot -Filter "*.json" -ErrorAction SilentlyContinue)
if ($outFiles.Count -eq 0) {
    Write-Fail "no runner outputs in $outRoot (check the terminal Experts log)"
}
$evidenceOut = Join-Path $evidence "mql5_out"
New-Item -ItemType Directory -Force -Path $evidenceOut | Out-Null
foreach ($f in $outFiles) {
    Copy-Item -LiteralPath $f.FullName -Destination (Join-Path $evidenceOut $f.Name) -Force
}

$shaLines = New-Object System.Collections.Generic.List[string]
foreach ($name in $runList) {
    foreach ($f in @("bundle.json", "ohlc.csv")) {
        $p = Join-Path (Join-Path $filesRoot $name) $f
        $h = (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLower()
        $shaLines.Add("$h  in/$name/$f")
    }
}
foreach ($f in (Get-ChildItem -LiteralPath $evidenceOut -Filter "*.json" | Sort-Object Name)) {
    $h = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLower()
    $shaLines.Add("$h  out/$($f.Name)")
}
[IO.File]::WriteAllText((Join-Path $evidence "sha256_manifest.txt"),
    (($shaLines -join "`n") + "`n"))

$python = if ($env:MQL5BOT_PYTHON) { $env:MQL5BOT_PYTHON } else { "python" }
$compare = Join-Path $repoRoot "tools\compare_dsl_parity.py"
$reportPath = Join-Path $evidence "compare_report.txt"
Write-Host "[dsl-parity] comparing: $python $compare $evidenceOut"
& $python $compare $evidenceOut --fixtures $gold 2>&1 | Tee-Object -FilePath $reportPath
$verdict = $LASTEXITCODE
if ($verdict -eq 0) {
    Write-Host "[dsl-parity] RESULT: EXACT parity (see $evidence)" -ForegroundColor Green
} else {
    Write-Host "[dsl-parity] RESULT: PARITY NOT PROVEN (see $reportPath)" -ForegroundColor Red
}
exit $verdict
