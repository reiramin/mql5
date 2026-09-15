<#
.SYNOPSIS
  AEGIS headless MT5 Strategy Tester wrapper (Phase 2).

.DESCRIPTION
  Thin, strict, logged wrapper around tools/run_mt5_backtest.py for the
  owner / Windows runner.  It ensures deterministic python invocation,
  captures every output stream into a run log under logs/, maps exit codes
  to clear messages and exits with the same code.

  Subcommands are delegated verbatim to the Python CLI:
    generate-set / generate-ini / matrix / parse / run / batch
  See `python tools\run_mt5_backtest.py --help` and tools/README.md.

  Prerequisites:
    - Windows with a (portable) MetaTrader 5 terminal
    - python on PATH (or set MQL5BOT_PYTHON to the interpreter path)

  Examples:
    powershell -ExecutionPolicy Bypass -File tools\run_mt5_backtest.ps1 `
        generate-ini --symbol EURUSD --timeframe H1 --input InpStrategy=0
    powershell -ExecutionPolicy Bypass -File tools\run_mt5_backtest.ps1 `
        run --terminal-dir D:\MT5 --data-folder D:\MT5 --out-dir results
    powershell -ExecutionPolicy Bypass -File tools\run_mt5_backtest.ps1 `
        batch --jobs jobs.json --terminal-dir D:\MT5 --data-folder D:\MT5

  Exit codes: 0 ok; 1 runtime/parse failure; 2 usage/config error;
  3 platform guard (run/batch on non-Windows); 4 wrapper failure
  (python missing, log write failed).

.NOTES
  Never claim a headless backtest result without the printed RESULT/log
  from a real run (HANDOFF section 10).  This sandbox has no terminal64.exe.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Command,

    # Remaining args are passed through to the Python CLI verbatim.
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PassThruArgs
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$cli = Join-Path $PSScriptRoot "run_mt5_backtest.py"
$logDir = Join-Path $repoRoot "logs"

$valid = @("generate-set", "generate-ini", "matrix", "parse", "run", "batch")
if ($valid -notcontains $Command) {
    Write-Host "[mt5tester] FAIL: unknown command '$Command' (valid: $($valid -join ', '))" -ForegroundColor Red
    exit 2
}

if (-not (Test-Path -LiteralPath $cli)) {
    Write-Host "[mt5tester] FAIL: CLI not found: $cli" -ForegroundColor Red
    exit 4
}

$python = "python"
if ($env:MQL5BOT_PYTHON) { $python = $env:MQL5BOT_PYTHON }

$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmss")
[IO.Directory]::CreateDirectory($logDir) | Out-Null
$runLog = Join-Path $logDir "mt5tester-$Command-$stamp.log"

try {
    # Quote any argument containing spaces so it survives the command line;
    # everything else passes through untouched (PowerShell 5.1 safe).
    $quoted = foreach ($arg in $PassThruArgs) {
        if ($arg -match "\s") { '"' + ($arg -replace '"', '\"') + '"' } else { $arg }
    }
    $argLine = $Command + " " + ($quoted -join " ")
    Write-Host "[mt5tester] running: $python $cli $argLine"
    "> $python $cli $argLine" | Out-File -LiteralPath $runLog -Encoding UTF8
    "> started $stamp UTC" | Out-File -LiteralPath $runLog -Encoding UTF8 -Append

    $proc = Start-Process -FilePath $python -ArgumentList @($cli, $argLine) `
        -RedirectStandardOutput $runLog -RedirectStandardError "$runLog.err" `
        -Wait -PassThru -NoNewWindow
    if (Test-Path -LiteralPath "$runLog.err") {
        Get-Content -LiteralPath "$runLog.err" -ErrorAction SilentlyContinue |
            ForEach-Object { Write-Host $_ -ForegroundColor Yellow }
    }
    if ($proc.ExitCode -eq 0) {
        Write-Host "[mt5tester] RESULT: OK ($Command)"
    } else {
        Write-Host "[mt5tester] RESULT: FAIL exit=$($proc.ExitCode) ($Command)" -ForegroundColor Red
    }
    Write-Host "[mt5tester] log: $runLog"
    exit $proc.ExitCode
} catch {
    Write-Host "[mt5tester] FAIL: $($_.Exception.Message)" -ForegroundColor Red
    exit 4
}
