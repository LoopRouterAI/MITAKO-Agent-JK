[CmdletBinding()]
param(
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root = Split-Path -Parent $PSScriptRoot
$Date = Get-Date -Format "yyyyMMdd"
$DeliveryDir = Join-Path $Root "dist"
$DefaultOutput = Join-Path $DeliveryDir "MITAKO_Agent-four-scenario-evidence-$Date.zip"
$ZipPath = if ($OutputPath) { [System.IO.Path]::GetFullPath($OutputPath) } else { $DefaultOutput }
$Stage = Join-Path $env:TEMP "MITAKO_Agent_evidence_stage_$Date"
$MediaRoot = Join-Path $Root "甲方沟通交付文档\四场景审核报告"
$MediaManifestSource = Join-Path $MediaRoot "media\manifest.json"
$Reports = @(
    "review_0816_blind_product_damage_611941.html",
    "review_0816_blind_product_damage_592717.html",
    "review_0816_blind_wrong_item_515028.html",
    "review_0816_blind_wrong_item_310508.html",
    "review_0816_blind_missing_item_289433.html",
    "review_0816_blind_missing_item_319303.html",
    "review_0816_blind_minor_refund_554611.html",
    "review_0816_blind_minor_refund_511007.html"
)

function Assert-NoTrackedChanges([string]$Message) {
    & git diff --quiet --
    if ($LASTEXITCODE -ne 0) { throw $Message }
    & git diff --cached --quiet --
    if ($LASTEXITCODE -ne 0) { throw $Message }
}

function Assert-NoUntrackedCode([string]$Message) {
    $untracked = @(& git -c core.quotepath=false ls-files --others --exclude-standard)
    if ($LASTEXITCODE -ne 0) { throw $Message }
    $unexpected = @($untracked | Where-Object {
        $_ -notlike "甲方沟通交付文档/四场景审核报告/media/*"
    })
    if ($unexpected.Count -gt 0) { throw "$Message`n$($unexpected -join "`n")" }
}

function Copy-File([string]$RelativePath, [string]$DestinationRelativePath = $RelativePath) {
    $source = Join-Path $Root $RelativePath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "缺少验收证据文件：$RelativePath"
    }
    $target = Join-Path $Stage $DestinationRelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $target -Force
}

Assert-NoTrackedChanges "工作树存在已修改文件，请先提交后再生成验收证据包。"
Assert-NoUntrackedCode "工作树存在未登记文件，请先清理或提交后再生成验收证据包。"
if (-not (Test-Path -LiteralPath $MediaManifestSource -PathType Leaf)) {
    throw "缺少离线媒体 manifest：$MediaManifestSource"
}
$mediaManifest = Get-Content -LiteralPath $MediaManifestSource -Raw -Encoding UTF8 | ConvertFrom-Json
$reportCount = @($mediaManifest.reports.PSObject.Properties).Count
$mediaAssetCount = @($mediaManifest.assets).Count
if ($reportCount -ne 8) { throw "媒体 manifest 未覆盖 8 份报告。" }
if ($mediaAssetCount -le 0) { throw "媒体 manifest 不得为空。" }

$stageFull = [System.IO.Path]::GetFullPath($Stage)
$tempFull = [System.IO.Path]::GetFullPath($env:TEMP)
if (-not $stageFull.StartsWith($tempFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "验收证据临时目录不在 TEMP 下：$stageFull"
}
if (Test-Path -LiteralPath $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
New-Item -ItemType Directory -Path $Stage -Force | Out-Null

Copy-File "甲方沟通交付文档\0817四场景审核业务理解与发布验收说明.html"
Copy-File "甲方沟通交付文档\0817四场景八份审核报告质量索引.html"
Copy-File "甲方沟通交付文档\0817甲方技术对接与私有化部署说明.html"
Copy-File "docs\release\2026-08-18-package-layout.md"
Copy-File "docs\release\2026-08-18-customer-update-notes.md"
Copy-File "docs\release\2026-08-18-developer-release-notes.md"
Copy-File "docs\release\2026-08-19-v3-beta-customer-notes.md"
Copy-File "docs\release\2026-08-19-v3-beta-developer-notes.md"
Copy-File "docs\testing\客服Agent用户沟通回归验收-20260819.md"
Copy-File "docs\release\2026-08-19-v3.1-beta-customer-notes.md"
Copy-File "docs\release\2026-08-19-v3.1-beta-developer-notes.md"
Copy-File "甲方沟通交付文档\0819客服Agent用户沟通问题闭环验收报告.html"
Copy-File "甲方沟通交付文档\0819v3.1_API与WebDemo功能与测试说明.html"
Copy-File "docs\测试反馈\MITAKO客服Agent用户沟通全量测试报告_20260818.pdf"
Copy-File "docs\testing\evidence\customer_chat_20260819_acceptance.json"
Copy-File "CHANGELOG.md"
foreach ($report in $Reports) {
    Copy-File "甲方沟通交付文档\四场景审核报告\$report" "甲方沟通交付文档\四场景审核报告\$report"
}

Copy-File "甲方沟通交付文档\四场景审核报告\media\manifest.json"
foreach ($asset in $mediaManifest.assets) {
    $relative = [string]$asset.asset
    if (-not $relative -or [System.IO.Path]::IsPathRooted($relative) -or $relative.Contains("..")) {
        throw "媒体路径非法：$relative"
    }
    $source = Join-Path $MediaRoot $relative.Replace("/", "\")
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "媒体文件缺失：$relative" }
    $actual = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne [string]$asset.sha256) { throw "媒体哈希不一致：$relative" }
    Copy-File "甲方沟通交付文档\四场景审核报告\$($relative.Replace('/', '\'))"
}

$packageManifest = [ordered]@{
    package_type = "four_scenario_offline_evidence"
    generated_at = (Get-Date).ToString("s")
    git_commit = (git rev-parse HEAD).Trim()
    report_count = $Reports.Count
    media_asset_count = $mediaAssetCount
    media_manifest_sha256 = (Get-FileHash -LiteralPath $MediaManifestSource -Algorithm SHA256).Hash.ToLowerInvariant()
    privacy_scope = "internal_review_only; contains sensitive user-submitted images"
    paired_customer_package = "MITAKO_Agent-customer-preview-$Date.zip"
    paired_internal_package = "MITAKO_Agent-internal-dev-$Date.zip"
}
$packageManifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $Stage "evidence-package-manifest.json") -Encoding UTF8
@"
# 四场景离线验收证据包

本包用于授权验收人员离线查看 8 份 HTML 报告及其 WebP 图片证据。

- 包类型：内部验收证据，不是运行包。
- 图片数量：$mediaAssetCount。
- 图片可能包含身份证、支付和其他用户提交材料，只允许在内部授权范围使用。
- 视频证据仍需启动正式 API 才能跳转时间和全屏查看。
- 代码、运行环境和 Java 联调资料请使用配套的内部研发包。
"@ | Set-Content -LiteralPath (Join-Path $Stage "证据包说明.md") -Encoding UTF8

New-Item -ItemType Directory -Path (Split-Path -Parent $ZipPath) -Force | Out-Null
if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $ZipPath -CompressionLevel Optimal
Remove-Item -LiteralPath $Stage -Recurse -Force

$sizeMb = [math]::Round((Get-Item -LiteralPath $ZipPath).Length / 1MB, 2)
Write-Host "[OK] Four-scenario evidence package: $ZipPath ($sizeMb MB)" -ForegroundColor Green
