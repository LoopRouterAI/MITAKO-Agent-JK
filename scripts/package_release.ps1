# -*- coding: utf-8 -*-
# 发布 ZIP — 仅维护方在验收通过后运行
# 用法: powershell -ExecutionPolicy Bypass -File scripts\package_release.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Date = Get-Date -Format "yyyyMMdd"
$ZipName = "MITAKO_Agent-release-$Date.zip"
$ZipPath = Join-Path (Split-Path -Parent $Root) $ZipName
$Stage = Join-Path $env:TEMP "MITAKO_Agent_stage_$Date"

Write-Host "=== MITAKO 发布打包 ===" -ForegroundColor Cyan
Write-Host "源: $Root"
Write-Host "输出: $ZipPath"

if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Path $Stage | Out-Null

$ExcludeDirs = @(
    "venv", "node_modules", "scratch", "__pycache__",
    ".codegraph", ".cursor", ".specify"
)
$ExcludeFiles = @(".env")

function Should-Skip($rel) {
    foreach ($d in $ExcludeDirs) {
        if ($rel -like "$d*" -or $rel -like "*\$d\*") { return $true }
    }
    if ($rel -like "tests\reports\*.html") { return $true }
    if ($rel -like "PPT-*\*" -or $rel -like "PPT-*") { return $true }
    if ($rel -eq ".env") { return $true }
    return $false
}

Get-ChildItem -Path $Root -Recurse -Force | ForEach-Object {
    $rel = $_.FullName.Substring($Root.Length + 1)
    if (Should-Skip $rel) { return }
    if ($_.PSIsContainer) { return }
    $dest = Join-Path $Stage $rel
    $destDir = Split-Path $dest -Parent
    if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
    Copy-Item $_.FullName $dest -Force
}

if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $ZipPath -CompressionLevel Optimal
Remove-Item $Stage -Recurse -Force

$sizeMb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 2)
Write-Host "[OK] 已生成 $ZipPath ($sizeMb MB)" -ForegroundColor Green
Write-Host "接收方: 解压 -> 开发上手.md -> setup_venv.bat -> npm install -> .env -> 一键启动"
