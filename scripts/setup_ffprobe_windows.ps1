param(
    [string]$Registry = "https://registry.npmmirror.com"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $Root
try {
    Write-Host "[1/3] 从 npm 镜像安装 ffprobe-static（仅本机开发依赖）..." -ForegroundColor Cyan
    npm install --no-save --ignore-scripts=false ffprobe-static@3.1.0 --registry=$Registry
    if ($LASTEXITCODE -ne 0) { throw "ffprobe-static 安装失败" }

    Write-Host "[2/3] 校验 ffprobe ..." -ForegroundColor Cyan
    $Ffprobe = (& node -e "console.log(require('ffprobe-static').path)").Trim()
    if (-not (Test-Path -LiteralPath $Ffprobe)) { throw "未找到 ffprobe 可执行文件" }
    & $Ffprobe -version | Select-Object -First 1
    if ($LASTEXITCODE -ne 0) { throw "ffprobe 无法执行" }

    Write-Host "[3/3] 配置方式" -ForegroundColor Cyan
    Write-Host "当前终端：`$env:REVIEW_FFPROBE_PATH='$Ffprobe'"
    Write-Host "持久配置：在 .env 中设置 REVIEW_FFPROBE_PATH=$Ffprobe"
    Write-Host "[OK] ffprobe 本机依赖可用。" -ForegroundColor Green
} finally {
    Pop-Location
}
