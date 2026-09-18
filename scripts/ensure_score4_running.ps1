$ErrorActionPreference = "Stop"
$Root = "C:\Users\berka\projeler\bnc"
Set-Location $Root
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$ft = Join-Path $Root ".venv\Scripts\freqtrade.exe"
$running = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and $_.CommandLine -match "freqtrade\.exe.*Score4WindowStrategy" }
if ($running) { exit 0 }
Start-Process -FilePath $ft -WorkingDirectory $Root `
  -ArgumentList @("trade","-c","user_data/config.json","--userdir","user_data","--strategy","Score4WindowStrategy") `
  -WindowStyle Hidden
