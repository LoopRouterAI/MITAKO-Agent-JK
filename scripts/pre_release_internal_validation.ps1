[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8015",
    [string]$VisualUrl = "http://127.0.0.1:7861",
    [string]$MinorSampleRoot = "",
    [switch]$RunModelBatch
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root = Split-Path -Parent $PSScriptRoot
$PythonCandidates = @(
    (Join-Path $Root ".venv\Scripts\python.exe"),
    (Join-Path $Root "venv\Scripts\python.exe")
)
$Python = $PythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Python) {
    throw "Internal Python environment not found: expected .venv or venv."
}

function Invoke-Step([string]$Name, [scriptblock]$Action) {
    Write-Host "[Internal release validation] $Name" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed. Customer packaging has been stopped."
    }
}

function Assert-Health([string]$Name, [string]$Url) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 8
        if ($response.StatusCode -ne 200) {
            throw "HTTP $($response.StatusCode)"
        }
    } catch {
        throw "$Name is not healthy at $Url. Start the internal source deployment before packaging. Detail: $($_.Exception.Message)"
    }
}

Push-Location $Root
try {
    Assert-Health "Main service" "$($BaseUrl.TrimEnd('/'))/api/v1/auth/status"
    Assert-Health "Visual review service" "$($VisualUrl.TrimEnd('/'))/api/health"

    $env:E2E_BASE_URL = $BaseUrl.TrimEnd('/')
    $env:VISUAL_WORKBENCH_BASE_URL = $VisualUrl.TrimEnd('/')
    $env:PYTHONIOENCODING = "utf-8"

    Invoke-Step "Frontend production build" { npm run build }
    Invoke-Step "Python core compilation" {
        & $Python -m py_compile main.py agent.py business_readiness_service.py review_service\service.py review_service\decision_policy.py review_service\advisory_assessment.py private_domain\service.py poc\visual_review_poc\order_info_adapter.py poc\visual_review_poc\official_reference_images.py scripts\sync_customer_order_info.py scripts\check_order_reference_integration.py scripts\check_documentation_release.py scripts\check_review_runtime_dependencies.py scripts\check_review_0717_four_samples.py scripts\check_minor_refund_144989.py scripts\check_review_submission_modes.py
    }
    Invoke-Step "Documentation and OpenAPI" { & $Python scripts\check_documentation_release.py }
    Invoke-Step "Private deployment API smoke" { & $Python scripts\check_private_deployment_api.py }
    Invoke-Step "Review label isolation" { & $Python scripts\check_review_input_isolation.py }
    Invoke-Step "Four-scenario SOP alignment" { & $Python scripts\check_review_sop_alignment.py }
    Invoke-Step "Media preprocessing and sampling" { & $Python scripts\check_review_media_preprocessing.py }
    Invoke-Step "Media upload safety" { & $Python -m unittest tests.review_service.test_media_upload_safety tests.visual_review.test_workbench_upload_safety }
    Invoke-Step "0717 review decision and timeline regression" { & $Python -m unittest tests.review_service.test_decision_policy_0717 tests.review_service.test_review_strength_and_forensics tests.visual_review.test_global_timeline_aggregation_0717 }
    Invoke-Step "Minor refund material coverage and privacy regression" { & $Python -m unittest tests.visual_review.test_minor_material_pipeline tests.visual_review.test_model_request_isolation tests.visual_review.test_report_evidence_rendering }
    Invoke-Step "Order baseline and on-demand official image regression" { & $Python -m unittest tests.visual_review.test_order_info_sync tests.visual_review.test_order_info_reconcile tests.visual_review.test_order_info_adapter tests.visual_review.test_official_reference_images tests.review_service.test_input_readiness }
    Invoke-Step "Visual workbench smoke" { & $Python scripts\check_visual_workbench_smoke.py }
    Invoke-Step "Customer Agent 0709 regression" { & $Python scripts\check_customer_agent_0709_regression.py }
    Invoke-Step "Customer Agent 0714 regression" { & $Python scripts\check_customer_agent_0714_regression.py }
    Invoke-Step "Frontend user isolation" { node tests\frontend\check_0714_user_isolation.mjs }
    Invoke-Step "Admin UI smoke" { & $Python scripts\check_admin_ui_smoke.py }
    Invoke-Step "Full API and browser pipeline" { & $Python tests\e2e\run_full_pipeline_e2e.py }
    Invoke-Step "Private-domain Agent workflow" { & $Python scripts\check_private_domain_agent_e2e.py }
    Invoke-Step "Private-domain 10k-group scale" { & $Python scripts\check_private_domain_10k_scale.py }

    $isolationDir = Join-Path $Root ("tmp\release-data-isolation-" + [guid]::NewGuid().ToString("N"))
    $previousDataDir = $env:MITAKO_DATA_DIR
    try {
        $env:MITAKO_DATA_DIR = $isolationDir
        Invoke-Step "Runtime data directory isolation" { & $Python scripts\check_data_isolation.py }
    } finally {
        if ($null -eq $previousDataDir) {
            Remove-Item Env:MITAKO_DATA_DIR -ErrorAction SilentlyContinue
        } else {
            $env:MITAKO_DATA_DIR = $previousDataDir
        }
    }

    if ($RunModelBatch) {
        Invoke-Step "Live multimodal review batch" { & $Python scripts\check_review_service_batch.py --samples "sample_003" --run-id "internal-release" }
    }
    if ($MinorSampleRoot) {
        if (-not (Test-Path -LiteralPath $MinorSampleRoot -PathType Container)) {
            throw "Minor sample root does not exist: $MinorSampleRoot"
        }
        Invoke-Step "144989 live minor-refund blind review" {
            & $Python scripts\check_minor_refund_144989.py --sample-root $MinorSampleRoot --base-url $BaseUrl
        }
    }

    Write-Host "[OK] Internal deployment, build, and release validation passed." -ForegroundColor Green
} finally {
    Pop-Location
}
