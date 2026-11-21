$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DataDir = Join-Path $ProjectRoot "data"
$DownloadDir = Join-Path $DataDir ".incremental-download"
$CacheDir = Join-Path $DataDir ".dukascopy-cache"
$BridgeScript = Join-Path $PSScriptRoot "socks5_http_connect_bridge.py"
New-Item -ItemType Directory -Force -Path $DownloadDir,$CacheDir | Out-Null
$Lock = Join-Path $DataDir ".daily-automation.lock"
if (Test-Path $Lock) {
  $age = (Get-Date) - (Get-Item $Lock).LastWriteTime
  if ($age.TotalHours -lt 8) { Write-Output "Another daily pipeline appears active; exiting safely."; exit 0 }
  Remove-Item $Lock -Force
}
Set-Content -Path $Lock -Value "started=$(Get-Date -Format o)"
$BridgeProcess = $null
$ProxyNames = @("NODE_USE_ENV_PROXY","HTTP_PROXY","HTTPS_PROXY")
$OldProxyValues = @{}
foreach ($name in $ProxyNames) { $OldProxyValues[$name] = [Environment]::GetEnvironmentVariable($name,"Process") }
try {
  $node = (Get-Command node.exe -ErrorAction Stop).Source
  $npx = (Get-Command npx.cmd -ErrorAction Stop).Source
  $version = (& $node --version).Trim()
  if ($version -notmatch '^v?(\d+)\.' -or [int]$Matches[1] -lt 20) { throw "Node.js 20+ required; found $version" }
  $listener = $false
  $probe = New-Object Net.Sockets.TcpClient
  try { $probe.Connect("127.0.0.1",18080); $listener=$true } catch {} finally {$probe.Dispose()}
  if (-not $listener) {
    $socks = New-Object Net.Sockets.TcpClient
    try {$socks.Connect("127.0.0.1",10808)} catch {throw "SOCKS5 proxy unavailable on 127.0.0.1:10808. Start VPN/proxy and retry."} finally {$socks.Dispose()}
    $python = (Get-Command py.exe -ErrorAction Stop).Source
    $BridgeProcess = Start-Process -FilePath $python -ArgumentList @("-3","-u",$BridgeScript) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $CacheDir "proxy-bridge.log") -RedirectStandardError (Join-Path $CacheDir "proxy-bridge-error.log")
    for($i=0;$i -lt 40;$i++){Start-Sleep -Milliseconds 250;$p=New-Object Net.Sockets.TcpClient;try{$p.Connect("127.0.0.1",18080);$listener=$true}catch{}finally{$p.Dispose()};if($listener){break};if($BridgeProcess.HasExited){throw "Proxy bridge exited; inspect proxy-bridge-error.log"}}
    if(-not $listener){throw "Proxy bridge did not start"}
  }
  $env:NODE_USE_ENV_PROXY="1";$env:HTTP_PROXY="http://127.0.0.1:18080";$env:HTTPS_PROXY="http://127.0.0.1:18080"
  # Remove prior run outputs so a failed/empty download can never reuse stale CSV data.
  Get-ChildItem $DownloadDir -Filter "*.csv" -File -ErrorAction SilentlyContinue | Remove-Item -Force
  $today=(Get-Date).ToUniversalTime().Date
  $from=$today.AddDays(-10).ToString("yyyy-MM-dd")
  $to=$today.AddDays(1).ToString("yyyy-MM-dd")
  Write-Output "Downloading EURUSD M1 BID overlap window $from to $to (UTC dates; end exclusive)"
  $downloadArgs=@("--yes","dukascopy-node@1.51.1","-i","eurusd","-from",$from,"-to",$to,"-t","m1","-p","bid","-utc","0","-v","-f","csv","-dir",$DownloadDir,"-bs","2","-bp","5000","-r","5","-ch","-chpath",$CacheDir)
  Push-Location $ProjectRoot
  try { & $npx @downloadArgs; if($LASTEXITCODE -ne 0){throw "Dukascopy downloader failed with exit code $LASTEXITCODE"} } finally {Pop-Location}
  $incoming=Get-ChildItem $DownloadDir -Filter "*.csv" -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if(-not $incoming){throw "Downloader completed but no incremental CSV was produced"}
  Write-Output "Incremental file: $($incoming.FullName)"
  Push-Location $ProjectRoot
  try { & py -3 ".\scripts\daily_automation_pipeline.py" --incremental $incoming.FullName; if($LASTEXITCODE -ne 0){throw "Daily Python pipeline failed with exit code $LASTEXITCODE"} } finally {Pop-Location}
  Write-Output "DAILY AUTOMATION COMPLETED"
} catch {
  $err = $_ | Out-String
  $logDir=Join-Path $ProjectRoot "Modules\Elliott_Waves\Evaluation\automation"
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
  Add-Content -Path (Join-Path $logDir "daily_pipeline_errors.log") -Value ("["+(Get-Date -Format o)+"] "+$err)
  Write-Error $err
  exit 1
} finally {
  foreach($name in $ProxyNames){[Environment]::SetEnvironmentVariable($name,$OldProxyValues[$name],"Process")}
  if($BridgeProcess -and -not $BridgeProcess.HasExited){Stop-Process -Id $BridgeProcess.Id -Force -ErrorAction SilentlyContinue}
  Remove-Item $Lock -Force -ErrorAction SilentlyContinue
}
