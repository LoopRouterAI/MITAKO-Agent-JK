[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8015",
    [string]$VisualUrl = "http://127.0.0.1:7861",
    [switch]$IncludeSecrets,
    [switch]$RunModelBatch,
    [switch]$ReuseValidatedAcceptanceEvidence
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root = Split-Path -Parent $PSScriptRoot
$Date = Get-Date -Format "yyyyMMdd"
$Stage = Join-Path $env:TEMP "MITAKO_Agent_internal_stage_$Date"
$DeliveryDir = Join-Path $Root "dist"
$ZipPath = Join-Path $DeliveryDir "MITAKO_Agent-internal-dev-$Date.zip"
$PythonCandidates = @(
    (Join-Path $Root ".venv\Scripts\python.exe"),
    (Join-Path $Root "venv\Scripts\python.exe")
)
$Python = $PythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Python) { throw "Missing Python runtime: expected .venv or venv." }
$GitCommit = (git rev-parse HEAD).Trim()
$RuntimeSnapshots = [System.Collections.Generic.List[object]]::new()

function Assert-NoTrackedChanges([string]$Message) {
    & git diff --quiet --
    if ($LASTEXITCODE -ne 0) { throw $Message }
    & git diff --cached --quiet --
    if ($LASTEXITCODE -ne 0) { throw $Message }
}

function Assert-NoUntrackedCode([string]$Message) {
    # 门禁命令保持稳定：git ls-files --others --exclude-standard
    $untracked = @(& git -c core.quotepath=false ls-files --others --exclude-standard)
    if ($LASTEXITCODE -ne 0) { throw $Message }
    $allowedGenerated = @($untracked | Where-Object { $_ -like "甲方沟通交付文档/四场景审核报告/media/*" })
    $unexpected = @($untracked | Where-Object { $allowedGenerated -notcontains $_ })
    if ($unexpected.Count -gt 0) { throw "$Message`n$($unexpected -join "`n")" }
}

function Get-RepositoryRelativePath([string]$Path) {
    $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd([char[]]"\/")
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $prefix = $fullRoot + [System.IO.Path]::DirectorySeparatorChar
    if (-not $fullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside repository root: $fullPath"
    }
    return $fullPath.Substring($prefix.Length)
}

Assert-NoTrackedChanges "Working tree contains tracked changes. Commit them before creating an auditable internal package."
Assert-NoUntrackedCode "Working tree contains untracked code. Commit or remove it before creating an auditable internal package."

function Invoke-InternalValidation {
    if ($RunModelBatch -and $ReuseValidatedAcceptanceEvidence) {
        throw "RunModelBatch and ReuseValidatedAcceptanceEvidence cannot be used together."
    }
    if ($ReuseValidatedAcceptanceEvidence) {
        Write-Host "[Release] Reusing frozen four-scenario acceptance; full API/model E2E is skipped for this packaging-only release." -ForegroundColor Yellow
        return
    }
    $modelBatchParams = @{}
    if ($RunModelBatch) { $modelBatchParams.RunModelBatch = $true }
    & (Join-Path $PSScriptRoot "pre_release_internal_validation.ps1") -BaseUrl $BaseUrl -VisualUrl $VisualUrl @modelBatchParams
}

Invoke-InternalValidation
Assert-NoTrackedChanges "Release validation changed tracked files. Review and commit them before packaging."
Assert-NoUntrackedCode "Release validation created untracked code. Review it before packaging."
$FourScenarioAcceptanceSource = Join-Path $Root "tests\reports\review_0816_four_scenario_blind_results_latest.json"
if (-not (Test-Path -LiteralPath $FourScenarioAcceptanceSource -PathType Leaf)) {
    throw "Four-scenario acceptance evidence is missing: $FourScenarioAcceptanceSource"
}
& $Python -c "import pathlib,sys; sys.path.insert(0,sys.argv[2]); from scripts.check_release_packages import _verify_current_four_scenario_acceptance; _verify_current_four_scenario_acceptance(pathlib.Path(sys.argv[1]))" $FourScenarioAcceptanceSource $Root
if ($LASTEXITCODE -ne 0) { throw "Four-scenario acceptance evidence is invalid." }

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
    if ((Get-Item -LiteralPath $source).PSIsContainer) {
        New-Item -ItemType Directory -Path $target -Force | Out-Null
        Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination $target -Recurse -Force
    } else {
        $parent = Split-Path -Parent $target
        if (-not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        Copy-Item -LiteralPath $source -Destination $target -Force
    }
}

function Copy-LatestReport([string]$Pattern, [string]$TargetRelativePath) {
    $source = Get-ChildItem -LiteralPath (Join-Path $Root "tests\reports") -File -Filter $Pattern |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $source) { throw "Missing required test report: $Pattern" }
    $target = Join-Path $Stage $TargetRelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath $source.FullName -Destination $target -Force
    $RuntimeSnapshots.Add([ordered]@{
        source_type = "runtime_report_snapshot"
        source_path = (Get-RepositoryRelativePath $source.FullName).Replace("\", "/")
        packaged_path = $TargetRelativePath.Replace("\", "/")
        sha256 = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    })
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

$InternalExcludedPrefixes = @(
    "docs\三大审核场景的小量样本\sample_002\",
    "docs\三大审核场景的小量样本\sample_003\",
    "docs\三大审核场景的小量样本\sample_004\",
    "甲方沟通交付文档\四场景审核报告\media\"
)

Reset-Stage

Write-Host "[1/5] Copy committed source ..." -ForegroundColor Cyan
git -c core.quotepath=false ls-files | ForEach-Object {
    $relativePath = $_.Replace("/", "\")
    $excluded = $InternalExcludedPrefixes | Where-Object {
        $relativePath.StartsWith($_, [System.StringComparison]::OrdinalIgnoreCase)
    }
    if (-not $excluded) { Copy-Path $relativePath }
}
Copy-Path ".env.example"
if ($IncludeSecrets) { Copy-Path ".env" }

$databaseNames = @()
Write-Host "[2/5] Handle optional runtime secrets ..." -ForegroundColor Cyan
if ($IncludeSecrets) {
    $databaseNames = @("admin.db", "auth.db", "handoff.db", "private_domain.db", "review_service.db")
    foreach ($databaseName in $databaseNames) {
        $source = Join-Path $Root "data\$databaseName"
        if (-not (Test-Path -LiteralPath $source)) { throw "Missing runtime database: $databaseName" }
        $target = Join-Path $Stage "data\$databaseName"
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        & $Python -c "import sqlite3,sys; src=sqlite3.connect(sys.argv[1]); dst=sqlite3.connect(sys.argv[2]); src.backup(dst); dst.close(); src.close()" $source $target
        if ($LASTEXITCODE -ne 0) { throw "Database snapshot failed: $databaseName" }
        $RuntimeSnapshots.Add([ordered]@{
            source_type = "runtime_database_snapshot"
            packaged_path = "data/$databaseName"
            sha256 = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
        })
    }
}

Write-Host "[3/5] Copy runnable samples and acceptance evidence ..." -ForegroundColor Cyan
Copy-SafeSampleLabels
Copy-Path "poc\visual_review_poc\sample_videos"
Copy-Path "tests\reports\customer_order_info_sync_strict_verify_20260720.json"
Copy-Path "tests\reports\customer_order_info_reconcile_applied_20260720.json"
Copy-Path "tests\reports\customer_order_info_integration_strict_final_20260720.json"
Copy-Path "tests\reports\dynamic_material_capacity_http_latest.json"
Copy-Path "tests\reports\dynamic_material_capacity_http_51_20260730.json"
Copy-Path "tests\reports\dynamic_material_capacity_http_62_20260730.json"
Copy-Path "tests\reports\review_0816_four_scenario_blind_results_latest.json"
Copy-Path "甲方沟通交付文档\0817四场景审核业务理解与发布验收说明.html"
Copy-Path "甲方沟通交付文档\0817四场景八份审核报告质量索引.html"
Copy-Path "甲方沟通交付文档\0817甲方技术对接与私有化部署说明.html"
Copy-Path "docs\delivery\甲方技术对接与私有化部署说明.html"
Copy-Path "docs\release\2026-08-18-package-layout.md"
$fourScenarioPublicReportDir = "甲方沟通交付文档\四场景审核报告"
foreach ($reportName in @(
    "review_0816_blind_product_damage_611941.html",
    "review_0816_blind_product_damage_592717.html",
    "review_0816_blind_wrong_item_515028.html",
    "review_0816_blind_wrong_item_310508.html",
    "review_0816_blind_missing_item_289433.html",
    "review_0816_blind_missing_item_319303.html",
    "review_0816_blind_minor_refund_554611.html",
    "review_0816_blind_minor_refund_511007.html"
)) { Copy-Path "$fourScenarioPublicReportDir\$reportName" }
$fourScenarioAcceptance = Get-Content -LiteralPath $FourScenarioAcceptanceSource -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($case in $fourScenarioAcceptance.cases) {
    foreach ($propertyName in @("report_json", "report_html")) {
        $relativePath = [string]$case.$propertyName
        if (-not $relativePath) { throw "Four-scenario acceptance case is missing $propertyName." }
        Copy-Path $relativePath.Replace("/", "\")
    }
}
Copy-LatestReport "full_pipeline_*.html" "tests\reports\full_pipeline_latest.html"
Copy-LatestReport "auth_strict_*.html" "tests\reports\auth_strict_latest.html"
Copy-LatestReport "private_deployment_api_smoke_*.json" "tests\reports\private_deployment_api_smoke_latest.json"

$evidenceFiles = @(
    "docs\delivery\openapi.yaml",
    "docs\delivery\review-advisory-api.md",
    "docs\delivery\after-sales-agent-integration.md",
    "docs\product\四场景审核业务决策与报告契约-20260812.md",
    "甲方沟通交付文档\0817四场景审核业务理解与发布验收说明.html",
    "甲方沟通交付文档\0817四场景八份审核报告质量索引.html",
    "甲方沟通交付文档\0817甲方技术对接与私有化部署说明.html",
    "docs\delivery\甲方技术对接与私有化部署说明.html",
    "docs\release\2026-08-19-v3-beta-customer-notes.md",
    "docs\release\2026-08-19-v3-beta-developer-notes.md",
    "docs\testing\客服Agent用户沟通回归验收-20260819.md",
    "docs\release\2026-08-19-v3.1-beta-customer-notes.md",
    "docs\release\2026-08-19-v3.1-beta-developer-notes.md",
    "甲方沟通交付文档\0819客服Agent用户沟通问题闭环验收报告.html",
    "甲方沟通交付文档\0819v3.1_API与WebDemo功能与测试说明.html",
    "tests\reports\review_0816_four_scenario_blind_results_latest.json",
    "tests\reports\customer_order_info_sync_strict_verify_20260720.json",
    "tests\reports\customer_order_info_reconcile_applied_20260720.json",
    "tests\reports\customer_order_info_integration_strict_final_20260720.json",
    "tests\reports\dynamic_material_capacity_http_latest.json",
    "tests\reports\dynamic_material_capacity_http_51_20260730.json",
    "tests\reports\dynamic_material_capacity_http_62_20260730.json",
    "tests\reports\full_pipeline_latest.html",
    "tests\reports\auth_strict_latest.html",
    "tests\reports\private_deployment_api_smoke_latest.json",
    "甲方沟通交付文档\四场景审核报告\review_0816_blind_product_damage_611941.html",
    "甲方沟通交付文档\四场景审核报告\review_0816_blind_product_damage_592717.html",
    "甲方沟通交付文档\四场景审核报告\review_0816_blind_wrong_item_515028.html",
    "甲方沟通交付文档\四场景审核报告\review_0816_blind_wrong_item_310508.html",
    "甲方沟通交付文档\四场景审核报告\review_0816_blind_missing_item_289433.html",
    "甲方沟通交付文档\四场景审核报告\review_0816_blind_missing_item_319303.html",
    "甲方沟通交付文档\四场景审核报告\review_0816_blind_minor_refund_554611.html",
    "甲方沟通交付文档\四场景审核报告\review_0816_blind_minor_refund_511007.html"
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
    content_provenance = "Committed source is bound to git_commit; generated reports and optional databases are listed as runtime snapshots."
    secrets_included = [bool]$IncludeSecrets
    env_included = (Test-Path -LiteralPath (Join-Path $Stage ".env"))
    databases = $databaseNames
    runtime_snapshots = @($RuntimeSnapshots)
    samples = @("sample_labels.json (report evaluation only)", "visual_review_poc/sample_videos")
    evidence = $evidenceHashes
    package_layout = "source_and_docs_without_large_sample_media"
    evidence_package = "MITAKO_Agent-four-scenario-evidence-$Date.zip"
    excluded = @(".venv", "venv", "node_modules", ".git", ".codegraph", "tmp", "logs", "archive", "sample_001", "data/review_jobs", "120G customer assets", "docs/三大审核场景的小量样本/sample_002-004", "甲方沟通交付文档/四场景审核报告/media")
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Stage "internal-package-manifest.json") -Encoding UTF8

Write-Host "[4/5] Validate internal package boundary ..." -ForegroundColor Cyan
$required = @(
    "main.py",
    "我方内部开发文档\Java开发部署与联调指南.md",
    "我方内部开发文档\内部研发包交付说明.md",
    "docs\delivery\openapi.yaml",
    "docs\delivery\review-advisory-api.md",
    "docs\delivery\after-sales-agent-integration.md",
    "docs\delivery\java-client-sample.md",
    "docs\product\四场景审核业务决策与报告契约-20260812.md",
    "甲方沟通交付文档\0817四场景审核业务理解与发布验收说明.html",
    "甲方沟通交付文档\0817四场景八份审核报告质量索引.html",
    "甲方沟通交付文档\0817甲方技术对接与私有化部署说明.html",
    "docs\delivery\甲方技术对接与私有化部署说明.html",
    "docs\release\2026-08-18-package-layout.md",
    "docs\release\2026-08-18-developer-release-notes.md",
    "docs\release\2026-08-18-customer-update-notes.md",
    "docs\三大审核场景的小量样本\sample_labels.json",
    "scripts\pre_release_internal_validation.ps1",
    "tests\reports\review_0816_four_scenario_blind_results_latest.json",
    "tests\reports\dynamic_material_capacity_http_latest.json",
    "tests\reports\dynamic_material_capacity_http_51_20260730.json",
    "tests\reports\dynamic_material_capacity_http_62_20260730.json",
    "tests\reports\customer_order_info_sync_strict_verify_20260720.json",
    "tests\reports\customer_order_info_reconcile_applied_20260720.json",
    "tests\reports\customer_order_info_integration_strict_final_20260720.json"
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
if (-not $IncludeSecrets) {
    if (Test-Path -LiteralPath (Join-Path $Stage ".env")) {
        throw "Internal package contains .env without -IncludeSecrets."
    }
    $packagedDatabases = Get-ChildItem -LiteralPath (Join-Path $Stage "data") -File -Filter "*.db" -ErrorAction SilentlyContinue
    if ($packagedDatabases) { throw "Internal package contains runtime databases without -IncludeSecrets." }
}

Write-Host "[5/5] Create internal development ZIP ..." -ForegroundColor Cyan
New-Item -ItemType Directory -Path $DeliveryDir -Force | Out-Null
if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $ZipPath -CompressionLevel Optimal
Remove-Item -LiteralPath $Stage -Recurse -Force

$sizeMb = [math]::Round((Get-Item -LiteralPath $ZipPath).Length / 1MB, 2)
Write-Host "[OK] Internal development package: $ZipPath ($sizeMb MB)" -ForegroundColor Green
