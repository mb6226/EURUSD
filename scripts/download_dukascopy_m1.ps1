$ErrorActionPreference = "Stop"
$FromDate = "2021-11-20"
$ToDate = "2026-11-20"  # exclusive
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DataDir = Join-Path $ProjectRoot "data"
$CacheDir = Join-Path $DataDir ".dukascopy-cache"
$ExpectedFile = Join-Path $DataDir "eurusd-m1-bid-$FromDate-$ToDate.csv"
$BridgeScript = Join-Path $PSScriptRoot "socks5_http_connect_bridge.py"
$BridgeLog = Join-Path $CacheDir "proxy-bridge.log"
$BridgeErrorLog = Join-Path $CacheDir "proxy-bridge-error.log"
New-Item -ItemType Directory -Force -Path $DataDir, $CacheDir | Out-Null

$NodeCommand = Get-Command node.exe -CommandType Application -ErrorAction SilentlyContinue
if (-not $NodeCommand) { throw "Node.js 20+ is required. node.exe was not found on PATH." }
$NodeVersion = (& $NodeCommand.Source --version).Trim()
if ($NodeVersion -notmatch '^v?(\d+)\.' -or [int]$Matches[1] -lt 20) {
    throw "Node.js 20+ is required. Detected version: $NodeVersion"
}
$NpxCommand = Get-Command npx.cmd -CommandType Application -ErrorAction SilentlyContinue
if (-not $NpxCommand) { throw "npx.cmd was not found. Repair the Node.js installation or PATH." }

# Keep the user's existing proxy environment intact after this run.
$ProxyNames = @("NODE_USE_ENV_PROXY", "HTTP_PROXY", "HTTPS_PROXY")
$OldProxyValues = @{}
foreach ($name in $ProxyNames) { $OldProxyValues[$name] = [Environment]::GetEnvironmentVariable($name, "Process") }
$BridgeProcess = $null

try {
    # Start a loopback-only HTTP CONNECT bridge if the local SOCKS5 proxy is available.
    $listener = $false
    $probe = New-Object System.Net.Sockets.TcpClient
    try { $probe.Connect("127.0.0.1", 18080); $listener = $true } catch { } finally { $probe.Dispose() }

    if (-not $listener) {
        $socksProbe = New-Object System.Net.Sockets.TcpClient
        try { $socksProbe.Connect("127.0.0.1", 10808) } catch {
            throw "Local SOCKS5 proxy is not listening on 127.0.0.1:10808. Start your proxy/VPN and rerun."
        } finally { $socksProbe.Dispose() }

        if (-not (Test-Path $BridgeScript)) { throw "Proxy bridge script not found: $BridgeScript" }
        $PythonCommand = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue
        if (-not $PythonCommand) { throw "Python launcher py.exe is required to start the local proxy bridge." }
        $BridgeProcess = Start-Process -FilePath $PythonCommand.Source -ArgumentList @("-3", "-u", $BridgeScript) -WindowStyle Hidden -PassThru -RedirectStandardOutput $BridgeLog -RedirectStandardError $BridgeErrorLog

        for ($i = 0; $i -lt 40; $i++) {
            Start-Sleep -Milliseconds 250
            $probe = New-Object System.Net.Sockets.TcpClient
            try { $probe.Connect("127.0.0.1", 18080); $listener = $true } catch { } finally { $probe.Dispose() }
            if ($listener) { break }
            if ($BridgeProcess.HasExited) { throw "Proxy bridge exited early. Check $BridgeErrorLog" }
        }
        if (-not $listener) { throw "Proxy bridge did not start on 127.0.0.1:18080. Check $BridgeErrorLog" }
    }

    $env:NODE_USE_ENV_PROXY = "1"
    $env:HTTP_PROXY = "http://127.0.0.1:18080"
    $env:HTTPS_PROXY = "http://127.0.0.1:18080"

    Write-Host "Node.js $NodeVersion detected."
    Write-Host "Local SOCKS5 proxy bridge ready; Node.js will use it for HTTPS."
    Write-Host "Dukascopy EURUSD M1: $FromDate to $ToDate (UTC, end exclusive)"
    Write-Host "BID | OHLCV | volume ON | flats excluded | CSV"
    Write-Host "Small batches, retries and cache are enabled for resume."

    Push-Location $ProjectRoot
    try {
        $dukaArgs = @("--yes", "dukascopy-node@1.51.1", "-i", "eurusd", "-from", $FromDate, "-to", $ToDate, "-t", "m1", "-p", "bid", "-utc", "0", "-v", "-f", "csv", "-dir", $DataDir, "-bs", "2", "-bp", "5000", "-r", "5", "-ch", "-chpath", $CacheDir)
        & $NpxCommand.Source @dukaArgs
        if ($LASTEXITCODE -ne 0) { throw "Downloader exited with code $LASTEXITCODE. Cache preserved; rerun this script to retry." }
    } finally { Pop-Location }
} finally {
    foreach ($name in $ProxyNames) {
        [Environment]::SetEnvironmentVariable($name, $OldProxyValues[$name], "Process")
    }
    if ($BridgeProcess -and -not $BridgeProcess.HasExited) {
        Stop-Process -Id $BridgeProcess.Id -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path $ExpectedFile)) { throw "Expected CSV was not found: $ExpectedFile" }
if ((Get-Item $ExpectedFile).Length -lt 1000) { throw "CSV is unexpectedly small; do not use it." }
Write-Host "Download created: $ExpectedFile"

