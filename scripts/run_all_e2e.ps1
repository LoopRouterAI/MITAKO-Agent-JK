$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "=== MITAKO 全量 E2E 回归 ===" -ForegroundColor Cyan

if (-not (Test-Path "venv\Scripts\python.exe")) {
    Write-Host "[错误] 请先创建 venv 并安装依赖" -ForegroundColor Red
    exit 1
}

$Py = Join-Path $Root "venv\Scripts\python.exe"
$Fail = $false

function Invoke-Step([string]$Name, [scriptblock]$Block) {
    Write-Host ""
    Write-Host "[$Name]" -ForegroundColor Yellow
    & $Block
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[失败] $Name" -ForegroundColor Red
        $script:Fail = $true
    }
}

function Stop-MitakoPorts {
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\kill_mitako_ports.ps1
}

function Start-Mitako([string]$Title) {
    Write-Host "启动服务：$Title"
    Start-Process -FilePath $Py -ArgumentList "main.py" -WindowStyle Hidden -WorkingDirectory $Root
    Start-Sleep -Seconds 6
}

Invoke-Step "0 释放端口" { Stop-MitakoPorts }
Invoke-Step "0A 前端构建" { npm run build }

Write-Host ""
Write-Host "[1 启动本地回归服务]" -ForegroundColor Yellow
$env:APP_PORT = "8000"
$env:HANDOFF_BACKEND = "hybrid"
$env:CHATWOOT_MOCK = "1"
$env:MITAKO_BUSINESS_DEMO_API_ENABLED = "1"
$env:MITAKO_AUTH_REQUIRED = "0"
$env:MITAKO_PROTECTED_API_AUTH_REQUIRED = "0"
$env:MITAKO_DEV_AUTH_BYPASS = "1"
Start-Mitako "MITAKO-E2E"

$DataGuardDir = Join-Path $Root ("tmp\e2e-data-" + [guid]::NewGuid().ToString("N"))
$env:MITAKO_DATA_DIR = $DataGuardDir
Invoke-Step "1A 数据隔离门禁" { & $Py scripts\check_data_isolation.py }
Invoke-Step "1B 租户迁移备份 dry-run" { & $Py scripts\check_auth_migration_dry_run.py }
Remove-Item Env:\MITAKO_DATA_DIR -ErrorAction SilentlyContinue
Remove-Item Env:\MITAKO_MOCK_DATA_FILE -ErrorAction SilentlyContinue
Remove-Item Env:\MITAKO_VIKING_MEMORY_DIR -ErrorAction SilentlyContinue
Remove-Item Env:\MITAKO_AUTH_DB_PATH -ErrorAction SilentlyContinue

Invoke-Step "2 full_pipeline" { & $Py tests\e2e\run_full_pipeline_e2e.py }
Invoke-Step "3 admin_ops" { & $Py tests\e2e\run_admin_operations_e2e.py }
Invoke-Step "4 enterprise" { & $Py tests\e2e\run_enterprise_production_e2e.py }
Invoke-Step "5 business_guard" { & $Py tests\e2e\run_mock_business_guard_e2e.py }
Invoke-Step "6 visual_workbench_smoke" { & $Py scripts\check_visual_workbench_smoke.py }
Invoke-Step "6B admin_ui_smoke" { & $Py scripts\check_admin_ui_smoke.py }

Invoke-Step "7 重启为严格鉴权模式" {
    Stop-MitakoPorts
    Start-Sleep -Seconds 2
    $env:MITAKO_AUTH_REQUIRED = "1"
    $env:MITAKO_PROTECTED_API_AUTH_REQUIRED = "1"
    $env:MITAKO_DEV_AUTH_BYPASS = "0"
    $env:MITAKO_BUSINESS_DEMO_API_ENABLED = "0"
    $env:MITAKO_JWT_SECRET = "mitako-e2e-local-secret-change-before-production"
    & $Py scripts\seed_auth.py
    Start-Mitako "MITAKO-E2E-AUTH"
}
Invoke-Step "8 auth_strict" { & $Py tests\e2e\run_auth_strict_e2e.py }
Invoke-Step "9 handoff_tenant_guard" { & $Py tests\e2e\run_handoff_tenant_guard_e2e.py }

Write-Host ""
Write-Host "[10 关闭测试服务]" -ForegroundColor Yellow
Stop-MitakoPorts

if ($Fail) {
    Write-Host "[FAIL] 存在失败套件，请查看上方输出和 tests\reports\" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] 全量 E2E 通过" -ForegroundColor Green
exit 0
