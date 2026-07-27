[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8015",
    [string]$VisualUrl = "http://127.0.0.1:7861"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root = Split-Path -Parent $PSScriptRoot
$Date = Get-Date -Format "yyyyMMdd"
$Stage = Join-Path $env:TEMP "MITAKO_Agent_internal_stage_$Date"
$ZipPath = Join-Path (Split-Path -Parent $Root) "MITAKO_Agent-internal-dev-$Date.zip"
$PythonCandidates = @(
    (Join-Path $Root ".venv\Scripts\python.exe"),
    (Join-Path $Root "venv\Scripts\python.exe")
)
$Python = $PythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Python) { throw "Missing Python runtime: expected .venv or venv." }
$GitCommit = (git rev-parse HEAD).Trim()
$TrackedChanges = @(git status --porcelain --untracked-files=normal)
if ($TrackedChanges.Count -gt 0) {
    throw "Working tree contains tracked or untracked changes. Commit them before creating an auditable internal package."
}

function Invoke-InternalValidation {
    & (Join-Path $PSScriptRoot "pre_release_internal_validation.ps1") -BaseUrl $BaseUrl -VisualUrl $VisualUrl
}

Invoke-InternalValidation
$TrackedChangesAfterValidation = @(git status --porcelain --untracked-files=normal)
if ($TrackedChangesAfterValidation.Count -gt 0) {
    throw "Release validation changed tracked files. Review and commit them before packaging."
}

function Reset-Stage {
    $fullStage = [System.IO.Path]::GetFullPath($Stage)
    $fullTemp = [System.IO.Path]::GetFullPath($env:TEMP)
    if (-not $fullStage.StartsWith($fullTemp, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe internal package stage path: $fullStage"
    }
    if (Test-Path -LiteralPath $fullStage) {
        Remove-Item -LiteralPath $fullStage -Recurse -Force
    }
    New-Item -ItemType Directory -Path $fullStage | Out-Null
}

function Copy-Path([string]$RelativePath) {
    $source = Join-Path $Root $RelativePath
    if (-not (Test-Path -LiteralPath $source)) { return }
    $target = Join-Path $Stage $RelativePath
    $parent = Split-Path -Parent $target
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Copy-Item -LiteralPath $source -Destination $target -Recurse -Force
}

function Copy-LatestReport([string]$Pattern, [string]$TargetRelativePath) {
    $source = Get-ChildItem -LiteralPath (Join-Path $Root "tests\reports") -File -Filter $Pattern |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $source) { throw "Missing required test report: $Pattern" }
    $target = Join-Path $Stage $TargetRelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath $source.FullName -Destination $target -Force
}

function Copy-SafeSampleLabels {
    $relativePath = "docs\三大审核场景的小量样本\sample_labels.json"
    $sourcePath = Join-Path $Root $relativePath
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        throw "Missing visual review sample labels: $relativePath"
    }

    $source = Get-Content -LiteralPath $sourcePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $source.samples) { throw "Invalid sample labels: samples is required." }

    $allowedScenarios = @("video_unboxing", "product_damage", "minor_material")
    $allowedLabels = @("positive", "negative", "review")
    $safeSamples = [ordered]@{}
    foreach ($property in $source.samples.PSObject.Properties) {
        $sampleId = [string]$property.Name
        $item = $property.Value
        if ($sampleId -notmatch '^sample_[0-9]{3}$') { throw "Invalid sample id: $sampleId" }
        if ($allowedScenarios -notcontains [string]$item.scenario) { throw "Invalid scenario for ${sampleId}: $($item.scenario)" }
        if ($allowedLabels -notcontains [string]$item.expected_predicted_label) { throw "Invalid expected label for ${sampleId}: $($item.expected_predicted_label)" }

        $safeItem = [ordered]@{
            scenario = [string]$item.scenario
            expected_predicted_label = [string]$item.expected_predicted_label
            human_conclusion = [string]$item.human_conclusion
        }
        if ($item.previous_human_conclusion) { $safeItem.previous_human_conclusion = [string]$item.previous_human_conclusion }
        if ($item.sample_type) { $safeItem.sample_type = [string]$item.sample_type }
        $safeSamples[$sampleId] = $safeItem
    }

    $safePayload = [ordered]@{
        schema_version = 1
        note = "人工结论只用于报告侧评测，不进入模型 Prompt。"
        usage_boundary = "report_evaluation_only"
        send_to_model = $false
        samples = $safeSamples
    }
    $targetPath = Join-Path $Stage $relativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $targetPath) -Force | Out-Null
    $safePayload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $targetPath -Encoding UTF8
}

Reset-Stage

Write-Host "[1/5] Copy committed source ..." -ForegroundColor Cyan
git -c core.quotepath=false ls-files | ForEach-Object { Copy-Path $_ }
Copy-Path ".env"
Copy-Path ".env.example"

Write-Host "[2/5] Snapshot runtime databases ..." -ForegroundColor Cyan
$databaseNames = @("admin.db", "auth.db", "handoff.db", "private_domain.db", "review_service.db")
foreach ($databaseName in $databaseNames) {
    $source = Join-Path $Root "data\$databaseName"
    if (-not (Test-Path -LiteralPath $source)) { throw "Missing runtime database: $databaseName" }
    $target = Join-Path $Stage "data\$databaseName"
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    & $Python -c "import sqlite3,sys; src=sqlite3.connect(sys.argv[1]); dst=sqlite3.connect(sys.argv[2]); src.backup(dst); dst.close(); src.close()" $source $target
    if ($LASTEXITCODE -ne 0) { throw "Database snapshot failed: $databaseName" }
}

Write-Host "[3/5] Copy runnable samples and small attachments ..." -ForegroundColor Cyan
Copy-Path "docs\三大审核场景的小量样本\sample_002"
Copy-Path "docs\三大审核场景的小量样本\sample_003"
Copy-Path "docs\三大审核场景的小量样本\sample_004"
Copy-SafeSampleLabels
Copy-Path "poc\visual_review_poc\sample_videos"
Copy-Path "data\chat_attachments"
Copy-Path "data\private_domain_uploads"
Copy-Path "tests\reports\customer_agent_0714_regression_latest.json"
Copy-Path "tests\reports\review_service_batch_latest.json"
Copy-Path "tests\reports\review_media_preprocessing_latest.json"
Copy-Path "tests\reports\review_0717_four_samples_20260717-final.json"
Copy-Path "tests\reports\minor_refund_144989_20260717-final.json"
Copy-LatestReport "minor_refund_144989_20260720_*.json" "tests\reports\minor_refund_144989_20260720-latest.json"
Copy-LatestReport "minor_refund_144989_20260720_*.html" "tests\reports\minor_refund_144989_20260720-latest.html"
Copy-LatestReport "review_0717_four_samples_20260720-617911-independent24-*.json" "tests\reports\review_617911_individual24_20260720-latest.json"
Copy-LatestReport "review_0717_four_samples_20260720-617911-independent24-*.html" "tests\reports\review_617911_individual24_20260720-latest.html"
Copy-Path "tests\reports\customer_order_info_sync_verify_20260720.json"
Copy-Path "tests\reports\customer_order_info_integration_20260720.json"
Copy-Path "tests\reports\customer_order_info_sync_strict_verify_20260720.json"
Copy-Path "tests\reports\customer_order_info_reconcile_applied_20260720.json"
Copy-Path "tests\reports\customer_order_info_integration_strict_final_20260720.json"
Copy-Path "tests\reports\review_submission_modes_20260717-final.json"
Copy-Path "tests\reports\review_submission_modes_20260717-final.html"
Copy-LatestReport "full_pipeline_*.html" "tests\reports\full_pipeline_latest.html"
Copy-LatestReport "auth_strict_*.html" "tests\reports\auth_strict_latest.html"
Copy-LatestReport "private_deployment_api_smoke_*.json" "tests\reports\private_deployment_api_smoke_latest.json"

$evidenceFiles = @(
    "docs\delivery\openapi.yaml",
    "docs\delivery\review-advisory-api.md",
    "docs\delivery\after-sales-agent-integration.md",
    "甲方沟通交付文档\0723客诉审核Agent接口联调与商务沟通说明.html",
    "我方内部开发文档\升级日志-2026-07-23-多源证据与接口联调.md",
    "甲方沟通交付文档\0723审核结论置信度与人工复审分级说明.html",
    "我方内部开发文档\升级日志-2026-07-23-审核建议契约与可选HTML.md",
    "甲方沟通交付文档\甲方测试版与本轮更新说明-2026-07-17.html",
    "甲方沟通交付文档\视觉审核逐帧与资料审核整改说明-2026-07-20.html",
    "甲方沟通交付文档\未成年人资料字段一致性审核升级说明-2026-07-20.html",
    "甲方沟通交付文档\订单SKU快照接入与审核安全升级说明-2026-07-20.html",
    "甲方沟通交付文档\0722订单资料与官方商品图按需接入说明.html",
    "甲方沟通交付文档\144989未成年人资料审核整改与验收报告.html",
    "甲方沟通交付文档\0717四样本审核工程整改与验收报告.html",
    "甲方沟通交付文档\0717网页端视频读取问题整改与验收报告.html",
    "我方内部开发文档\升级日志-2026-07-17-四样本审核.md",
    "我方内部开发文档\升级日志-2026-07-17.md",
    "我方内部开发文档\升级日志-2026-07-17-提交模式与双包.md",
    "我方内部开发文档\升级日志-2026-07-17-144989未成年人资料审核.md",
    "我方内部开发文档\升级日志-2026-07-20-未成年人资料字段一致性.md",
    "我方内部开发文档\升级日志-2026-07-20-视觉证据安全与SKU基准.md",
    "我方内部开发文档\升级日志-2026-07-22-订单基线与官方商品图按需接入.md",
    "docs\delivery\mitako-visual-evaluation-engineering-acceptance-20260716.html",
    "docs\delivery\mitako-0714-adversarial-acceptance-20260715.html",
    "我方内部开发文档\升级日志-2026-07-16.md",
    "tests\reports\customer_agent_0714_regression_latest.json",
    "tests\reports\review_service_batch_latest.json",
    "tests\reports\review_media_preprocessing_latest.json",
    "tests\reports\review_0717_four_samples_20260717-final.json",
    "tests\reports\minor_refund_144989_20260717-final.json",
    "tests\reports\minor_refund_144989_20260720-latest.json",
    "tests\reports\minor_refund_144989_20260720-latest.html",
    "tests\reports\customer_order_info_sync_verify_20260720.json",
    "tests\reports\customer_order_info_integration_20260720.json",
    "tests\reports\customer_order_info_sync_strict_verify_20260720.json",
    "tests\reports\customer_order_info_reconcile_applied_20260720.json",
    "tests\reports\customer_order_info_integration_strict_final_20260720.json",
    "tests\reports\review_submission_modes_20260717-final.json",
    "tests\reports\review_submission_modes_20260717-final.html",
    "tests\reports\full_pipeline_latest.html",
    "tests\reports\auth_strict_latest.html",
    "tests\reports\private_deployment_api_smoke_latest.json"
)
$evidenceHashes = @()
foreach ($relativePath in $evidenceFiles) {
    $evidencePath = Join-Path $Stage $relativePath
    if (-not (Test-Path -LiteralPath $evidencePath)) { throw "Missing evidence file: $relativePath" }
    $evidenceHashes += [ordered]@{
        path = $relativePath.Replace("\", "/")
        sha256 = (Get-FileHash -LiteralPath $evidencePath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

$manifest = @{
    generated_at = (Get-Date).ToString("s")
    git_commit = $GitCommit
    env_included = (Test-Path -LiteralPath (Join-Path $Stage ".env"))
    databases = $databaseNames
    samples = @("sample_002", "sample_003", "sample_004", "sample_labels.json (report evaluation only)", "visual_review_poc/sample_videos")
    evidence = $evidenceHashes
    excluded = @(".venv", "venv", "node_modules", ".git", ".codegraph", "tmp", "logs", "archive", "sample_001", "data/review_jobs", "120G customer assets")
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Stage "internal-package-manifest.json") -Encoding UTF8

Write-Host "[4/5] Validate internal package boundary ..." -ForegroundColor Cyan
$required = @(
    "main.py",
    ".env",
    "我方内部开发文档\Java开发部署与联调指南.md",
    "我方内部开发文档\升级日志-2026-07-23-审核建议契约与可选HTML.md",
    "我方内部开发文档\内部研发包交付说明.md",
    "我方内部开发文档\升级日志-2026-07-17.md",
    "我方内部开发文档\升级日志-2026-07-17-提交模式与双包.md",
    "我方内部开发文档\升级日志-2026-07-17-144989未成年人资料审核.md",
    "我方内部开发文档\升级日志-2026-07-20-未成年人资料字段一致性.md",
    "我方内部开发文档\升级日志-2026-07-20-视觉证据安全与SKU基准.md",
    "我方内部开发文档\升级日志-2026-07-22-订单基线与官方商品图按需接入.md",
    "我方内部开发文档\升级日志-2026-07-17-四样本审核.md",
    "我方内部开发文档\升级日志-2026-07-16.md",
    "我方内部开发文档\升级日志-2026-07-15.md",
    "docs\delivery\openapi.yaml",
    "docs\delivery\review-advisory-api.md",
    "docs\delivery\after-sales-agent-integration.md",
    "docs\delivery\java-client-sample.md",
    "docs\delivery\mitako-visual-evaluation-engineering-acceptance-20260716.html",
    "docs\delivery\mitako-0714-adversarial-acceptance-20260715.html",
    "docs\delivery\客服Agent与私域Agent正式接入前人工UAT指南_20260716.md",
    "甲方沟通交付文档\0717网页端视频读取问题整改与验收报告.html",
    "甲方沟通交付文档\0717四样本审核工程整改与验收报告.html",
    "甲方沟通交付文档\甲方测试版与本轮更新说明-2026-07-17.html",
    "甲方沟通交付文档\144989未成年人资料审核整改与验收报告.html",
    "甲方沟通交付文档\未成年人资料字段一致性审核升级说明-2026-07-20.html",
    "甲方沟通交付文档\订单SKU快照接入与审核安全升级说明-2026-07-20.html",
    "甲方沟通交付文档\0722订单资料与官方商品图按需接入说明.html",
    "甲方沟通交付文档\0723审核结论置信度与人工复审分级说明.html",
    "甲方沟通交付文档\0723客诉审核Agent接口联调与商务沟通说明.html",
    "我方内部开发文档\升级日志-2026-07-23-多源证据与接口联调.md",
    "docs\三大审核场景的小量样本\sample_labels.json",
    "scripts\pre_release_internal_validation.ps1",
    "data\review_service.db",
    "tests\reports\review_0717_four_samples_20260717-final.json",
    "tests\reports\minor_refund_144989_20260717-final.json",
    "tests\reports\minor_refund_144989_20260720-latest.json",
    "tests\reports\minor_refund_144989_20260720-latest.html",
    "tests\reports\customer_order_info_sync_verify_20260720.json",
    "tests\reports\customer_order_info_integration_20260720.json",
    "tests\reports\review_submission_modes_20260717-final.json",
    "tests\reports\review_submission_modes_20260717-final.html"
)
foreach ($relativePath in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $Stage $relativePath))) {
        throw "Internal package missing required file: $relativePath"
    }
}
$packagedLabelsPath = Join-Path $Stage "docs\三大审核场景的小量样本\sample_labels.json"
$packagedLabels = Get-Content -LiteralPath $packagedLabelsPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($packagedLabels.send_to_model -ne $false -or $packagedLabels.usage_boundary -ne "report_evaluation_only") {
    throw "Packaged sample labels violate the report-only boundary."
}
foreach ($blocked in @(".venv", "venv", "node_modules", ".git", ".codegraph", "tmp", "logs", "archive", "data\review_jobs")) {
    if (Test-Path -LiteralPath (Join-Path $Stage $blocked)) {
        throw "Internal package contains blocked path: $blocked"
    }
}

Write-Host "[5/5] Create internal development ZIP ..." -ForegroundColor Cyan
if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $ZipPath -CompressionLevel Optimal
Remove-Item -LiteralPath $Stage -Recurse -Force

$sizeMb = [math]::Round((Get-Item -LiteralPath $ZipPath).Length / 1MB, 2)
Write-Host "[OK] Internal development package: $ZipPath ($sizeMb MB)" -ForegroundColor Green
