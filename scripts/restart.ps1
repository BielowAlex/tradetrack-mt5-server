# Перезапуск MT5 Backend: зупинка Python (API + RQ workers), потім запуск API та N воркерів.
# Кожен воркер отримує свій MT5_QUEUE_INDEX (0,1,2,…) і MT5_PATH з .env (MT5_PATH_0, MT5_PATH_1, …).
# Запуск: .\scripts\restart.ps1   або   .\scripts\restart.ps1 -SkipKill

param(
	[switch] $SkipKill
)

$ProjectRoot = Split-Path $PSScriptRoot -Parent
$RedisUrl = "redis://localhost:6379/0"

# Завантажити .env (прості KEY=VALUE)
$EnvPath = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvPath) {
	Get-Content $EnvPath | ForEach-Object {
		if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
			$key = $matches[1].Trim()
			$val = $matches[2].Trim()
			[Environment]::SetEnvironmentVariable($key, $val, "Process")
		}
	}
}

$WorkersCount = 3
if ($env:MT5_QUEUES_NUM -match '^\d+$') { $WorkersCount = [int]$env:MT5_QUEUES_NUM }

if (-not $SkipKill) {
	Write-Host "Зупиняю процеси python.exe (API та RQ workers)..." -ForegroundColor Yellow
	Get-Process -Name python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
	Start-Sleep -Seconds 2
}

Push-Location $ProjectRoot

# 1) API (Hypercorn)
Write-Host "Запускаю API (Hypercorn)..." -ForegroundColor Green
Start-Process powershell -ArgumentList @(
	"-NoExit",
	"-Command",
	"Set-Location '$ProjectRoot'; hypercorn app.main:app --bind 0.0.0.0:8000"
)

Start-Sleep -Seconds 1

# 2) По одному вікну на кожен RQ worker з його MT5_PATH_i
for ($i = 0; $i -lt $WorkersCount; $i++) {
	$pathVar = "MT5_PATH_$i"
	$Mt5Path = (Get-Item -Path "Env:$pathVar" -ErrorAction SilentlyContinue).Value
	if (-not $Mt5Path) { $Mt5Path = (Get-Item -Path "Env:MT5_PATH" -ErrorAction SilentlyContinue).Value }
	if (-not $Mt5Path) { $Mt5Path = "C:\Program Files\mt5-instance$($i+1)\terminal64.exe" }
	$Mt5Path = $Mt5Path -replace "'", "''"
	$WorkerCmd = "Set-Location '$ProjectRoot'; `$env:MT5_QUEUE_INDEX='$i'; `$env:MT5_PATH='$Mt5Path'; python -m rq.cli worker --worker-class app.run_worker.WindowsSimpleWorker mt5_trades_$i --url $RedisUrl"
	Write-Host "Запускаю RQ worker $i (mt5_trades_$i)..." -ForegroundColor Green
	Start-Process powershell -ArgumentList "-NoExit", "-Command", $WorkerCmd
	Start-Sleep -Milliseconds 500
}

Pop-Location
Write-Host ("Done. 1 API + " + $WorkersCount + " workers. Close windows to stop.") -ForegroundColor Cyan
