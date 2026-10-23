# BurnoutIQ — Start Both Servers
# Usage: .\start.ps1   (opens backend on 8501 + frontend on 8600, then browser)

param(
    [int]$BackendPort  = 8501,
    [int]$FrontendPort = 8600
)

$root = $PSScriptRoot

$py = 'python'
$codexPy = 'C:\Users\Manis\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Get-Command python -ErrorAction SilentlyContinue) -and (Test-Path $codexPy)) {
    $py = $codexPy
}

Write-Host ''
Write-Host '  +----------------------------------+' -ForegroundColor Cyan
Write-Host '  ¦      BurnoutIQ  —  starting      ¦' -ForegroundColor Cyan
Write-Host '  +----------------------------------+' -ForegroundColor Cyan
Write-Host ''
Write-Host  Backend -> http://localhost:$BackendPort -ForegroundColor Yellow
Write-Host  Frontend -> http://localhost:$FrontendPort -ForegroundColor Green
Write-Host ''

$backend = Start-Process -FilePath $py `
    -ArgumentList "$root\dashboard_server.py --port $BackendPort `
 -WorkingDirectory $root -PassThru -WindowStyle Hidden

Write-Host   [1/2] Backend started (PID $($backend.Id)) -ForegroundColor Yellow
Start-Sleep -Seconds 2

$frontend = Start-Process -FilePath $py `
 -ArgumentList $root\frontend\serve.py --port $FrontendPort `
 -WorkingDirectory $root -PassThru -WindowStyle Hidden

Write-Host   [2/2] Frontend started (PID $($frontend.Id)) -ForegroundColor Green
Start-Sleep -Seconds 2

$url = http://localhost:$FrontendPort
Write-Host ''
Write-Host   Opening $url ... -ForegroundColor Cyan
Start-Process $url

Write-Host ''
Write-Host ' Both servers running. Press Ctrl+C to stop.' -ForegroundColor White
Write-Host ''

try { Wait-Process -Id $frontend.Id }
finally {
 Write-Host 
Shutting down... -ForegroundColor Red
 Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
 Stop-Process -Id $frontend.Id -ErrorAction SilentlyContinue
}
