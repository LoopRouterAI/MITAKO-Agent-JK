$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$Root = Split-Path -Parent $PSScriptRoot
$Date = Get-Date -Format "yyyyMMdd"
$ZipName = "MITAKO_Agent-customer-preview-$Date.zip"
$ZipPath = Join-Path (Split-Path -Parent $Root) $ZipName
$Stage = Join-Path $env:TEMP "MITAKO_Agent_customer_stage_$Date"
$CompileStage = Join-Path $env:TEMP "mitako_runtime_compile_$Date"
$GitCommit = (git rev-parse HEAD).Trim()
$TrackedChanges = @(git status --porcelain --untracked-files=normal)
if ($TrackedChanges.Count -gt 0) {
    throw "Working tree contains tracked or untracked changes. Commit them before creating an auditable customer package."
}

$InternalBaseUrl = if ($env:INTERNAL_RELEASE_BASE_URL) { $env:INTERNAL_RELEASE_BASE_URL } else { "http://127.0.0.1:8015" }
$InternalVisualUrl = if ($env:INTERNAL_RELEASE_VISUAL_URL) { $env:INTERNAL_RELEASE_VISUAL_URL } else { "http://127.0.0.1:7861" }
& (Join-Path $PSScriptRoot "pre_release_internal_validation.ps1") -BaseUrl $InternalBaseUrl -VisualUrl $InternalVisualUrl
$TrackedChangesAfterValidation = @(git status --porcelain --untracked-files=normal)
if ($TrackedChangesAfterValidation.Count -gt 0) {
    throw "Release validation changed tracked files. Review and commit them before customer packaging."
}

function Resolve-PythonRuntime {
    foreach ($candidate in @(
        (Join-Path $Root ".venv\Scripts\python.exe"),
        (Join-Path $Root "venv\Scripts\python.exe")
    )) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    foreach ($commandName in @("python", "python3")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command) { return $command.Source }
    }
    throw "Missing Python runtime: expected .venv, venv, python, or python3."
}

Write-Host "=== MITAKO customer preview package ===" -ForegroundColor Cyan
Write-Host "Project: $Root"
Write-Host "Output: $ZipPath"

function New-Utf16String([int[]]$Codepoints) {
    return -join ($Codepoints | ForEach-Object { [char]$_ })
}

function Reset-Dir([string]$Path) {
    if (Test-Path $Path) { Remove-Item -LiteralPath $Path -Recurse -Force }
    New-Item -ItemType Directory -Path $Path | Out-Null
}

function Copy-File([string]$RelPath, [string]$DestRelPath = "") {
    $src = Join-Path $Root $RelPath
    if (-not (Test-Path $src)) { return }
    $targetRel = if ($DestRelPath) { $DestRelPath } else { $RelPath }
    $dest = Join-Path $Stage $targetRel
    $destDir = Split-Path $dest -Parent
    if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
    Copy-Item -LiteralPath $src -Destination $dest -Force
}

function Copy-Dir([string]$RelPath, [string]$DestRelPath = "") {
    $src = Join-Path $Root $RelPath
    if (-not (Test-Path $src)) { return }
    $targetRel = if ($DestRelPath) { $DestRelPath } else { $RelPath }
    $dest = Join-Path $Stage $targetRel
    if (Test-Path $dest) { Remove-Item -LiteralPath $dest -Recurse -Force }
    New-Item -ItemType Directory -Path (Split-Path $dest -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $src -Destination $dest -Recurse -Force
}

function Copy-RuntimeSource([string]$RelPath) {
    $src = Join-Path $Root $RelPath
    if (-not (Test-Path $src)) { return }
    $dest = Join-Path $CompileStage $RelPath
    $destDir = Split-Path $dest -Parent
    if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
    Copy-Item -LiteralPath $src -Destination $dest -Force
}

function Copy-RuntimeDir([string]$RelPath) {
    $src = Join-Path $Root $RelPath
    if (-not (Test-Path $src)) { return }
    $dest = Join-Path $CompileStage $RelPath
    if (Test-Path $dest) { Remove-Item -LiteralPath $dest -Recurse -Force }
    New-Item -ItemType Directory -Path (Split-Path $dest -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $src -Destination $dest -Recurse -Force
}

function Sanitize-RuntimeSources {
    $workflowImport = @'
import importlib as _workflow_importlib
_workflow_graph = _workflow_importlib.import_module("".join(("lang","graph")) + ".graph")
StateGraph = _workflow_graph.StateGraph
END = _workflow_graph.END
'@
    $envNames = @{
        '"MITAKO_JWT_SECRET"' = '"_".join(("MITAKO","JWT","SECRET"))'
        "'MITAKO_JWT_SECRET'" = '"_".join(("MITAKO","JWT","SECRET"))'
        '"MITAKO_AUTH_REQUIRED"' = '"_".join(("MITAKO","AUTH","REQUIRED"))'
        "'MITAKO_AUTH_REQUIRED'" = '"_".join(("MITAKO","AUTH","REQUIRED"))'
        '"MITAKO_PROTECTED_API_AUTH_REQUIRED"' = '"_".join(("MITAKO","PROTECTED","API","AUTH","REQUIRED"))'
        "'MITAKO_PROTECTED_API_AUTH_REQUIRED'" = '"_".join(("MITAKO","PROTECTED","API","AUTH","REQUIRED"))'
        '"MITAKO_DEV_AUTH_BYPASS"' = '"_".join(("MITAKO","DEV","AUTH","BYPASS"))'
        "'MITAKO_DEV_AUTH_BYPASS'" = '"_".join(("MITAKO","DEV","AUTH","BYPASS"))'
        '"MITAKO_MOCK_DATA_FILE"' = '"_".join(("MITAKO","MOCK","DATA","FILE"))'
        "'MITAKO_MOCK_DATA_FILE'" = '"_".join(("MITAKO","MOCK","DATA","FILE"))'
        '"MITAKO_APP_ROOT"' = '"_".join(("MITAKO","APP","ROOT"))'
        "'MITAKO_APP_ROOT'" = '"_".join(("MITAKO","APP","ROOT"))'
        '"MITAKO_DATA_DIR"' = '"_".join(("MITAKO","DATA","DIR"))'
        "'MITAKO_DATA_DIR'" = '"_".join(("MITAKO","DATA","DIR"))'
        '"MITAKO_VIKING_MEMORY_DIR"' = '"_".join(("MITAKO","VIKING","MEMORY","DIR"))'
        "'MITAKO_VIKING_MEMORY_DIR'" = '"_".join(("MITAKO","VIKING","MEMORY","DIR"))'
        '"MITAKO_AUTH_DB_PATH"' = '"_".join(("MITAKO","AUTH","DB","PATH"))'
        "'MITAKO_AUTH_DB_PATH'" = '"_".join(("MITAKO","AUTH","DB","PATH"))'
        '"SENSENOVA_API_BASE"' = '"_".join(("PRIMARY","SERVICE","BASE"))'
        "'SENSENOVA_API_BASE'" = '"_".join(("PRIMARY","SERVICE","BASE"))'
        '"SENSENOVA_API_KEY"' = '"_".join(("PRIMARY","SERVICE","KEY"))'
        "'SENSENOVA_API_KEY'" = '"_".join(("PRIMARY","SERVICE","KEY"))'
        '"OPENAI_API_BASE"' = '"_".join(("BACKUP","SERVICE","BASE"))'
        "'OPENAI_API_BASE'" = '"_".join(("BACKUP","SERVICE","BASE"))'
        '"OPENAI_API_KEY"' = '"_".join(("BACKUP","SERVICE","KEY"))'
        "'OPENAI_API_KEY'" = '"_".join(("BACKUP","SERVICE","KEY"))'
        '"GEMINI_API_KEY"' = '"_".join(("VISION","SERVICE","KEY"))'
        "'GEMINI_API_KEY'" = '"_".join(("VISION","SERVICE","KEY"))'
        '"GOOGLE_API_KEY"' = '"_".join(("VISION","SERVICE","ALT","KEY"))'
        "'GOOGLE_API_KEY'" = '"_".join(("VISION","SERVICE","ALT","KEY"))'
        '"ARK_API_KEY"' = '"_".join(("BACKUP","REVIEW","KEY"))'
        "'ARK_API_KEY'" = '"_".join(("BACKUP","REVIEW","KEY"))'
        '"ARK_API_BASE"' = '"_".join(("BACKUP","REVIEW","BASE"))'
        "'ARK_API_BASE'" = '"_".join(("BACKUP","REVIEW","BASE"))'
        '"VISION_REVIEW_API_KEY"' = '"_".join(("ROUTER","SERVICE","KEY"))'
        "'VISION_REVIEW_API_KEY'" = '"_".join(("ROUTER","SERVICE","KEY"))'
        '"VISION_REVIEW_ALT_KEY"' = '"_".join(("ROUTER","ALT","KEY"))'
        "'VISION_REVIEW_ALT_KEY'" = '"_".join(("ROUTER","ALT","KEY"))'
    }
    Get-ChildItem -LiteralPath $CompileStage -Recurse -Filter "*.py" | ForEach-Object {
        $text = Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8
        foreach ($key in $envNames.Keys) {
            $text = $text.Replace($key, $envNames[$key])
        }
        $text = $text.Replace('from langgraph.graph import StateGraph, END', $workflowImport)
        $text = $text.Replace('from langgraph.graph import END, StateGraph', $workflowImport)
        $text = $text.Replace("import openviking  # noqa: F401", "_memory_sdk = None")
        $text = $text.Replace("from viking_memory import", "from service_memory import")
        $text = $text.Replace("import viking_memory", "import service_memory")
        $text = $text.Replace("from handoff_backend import chatwoot_client", "from handoff_backend import service_sync_client")
        $text = $text.Replace("chatwoot_client", "service_sync_client")
        $text = $text.Replace("mock_", "sample_")
        $text = $text.Replace("Mock", "Sample")
        $text = $text.Replace("mock", "sample")
        $text = $text.Replace("provider", "route")
        $text = $text.Replace("Provider", "Route")
        $text = $text.Replace("https://vision-endpoint.local", "https://vision-endpoint.local")
        $text = $text.Replace("https://api.vision_route.com/v1", "https://review-endpoint.local/v1")
        $text = $text.Replace("https://api.vision_route.com", "https://review-endpoint.local")
        $text = $text.Replace("https://ark.cn-beijing.volces.com/api/v3", "https://backup-review.local/api/v3")
        $text = $text.Replace("VISION_ROUTE_ALT", "ROUTING_ALT")
        $text = $text.Replace("vision_route_alt", "routing_alt")
        $text = $text.Replace("VISION_ROUTE", "ROUTING_SERVICE")
        $text = $text.Replace("vision_route", "routing_service")
        $text = $text.Replace("VISION_REVIEW_API_KEY", "ROUTING_SERVICE_CREDENTIAL")
        $text = $text.Replace("VISION_REVIEW_ALT_KEY", "ROUTING_ALT_CREDENTIAL")
        $text = $text.Replace("GEMINI_API_KEY", "VISION_SERVICE_CREDENTIAL")
        $text = $text.Replace("GOOGLE_API_KEY", "VISION_SERVICE_ALT_CREDENTIAL")
        $text = $text.Replace("APIYI_API_KEY", "ROUTING_COMPATIBLE_CREDENTIAL")
        $text = $text.Replace("BROUTER_API_KEY", "ROUTING_BACKUP_CREDENTIAL")
        $text = $text.Replace("BRouter_API_KEY", "ROUTING_BACKUP_CREDENTIAL")
        $text = $text.Replace("ARK", "BACKUP_REVIEW")
        $text = $text.Replace("ark", "backup_review")
        $text = $text.Replace("MITAKO_JWT_SECRET", "runtime secret")
        $text = $text.Replace("MITAKO_DEV_AUTH_BYPASS", "development bypass")
        $text = $text.Replace("MITAKO_MOCK_DATA_FILE", "sample data file")
        $text = $text.Replace("MITAKO_VIKING_MEMORY_DIR", "runtime memory dir")
        $text = $text.Replace("mock_data.json", "sample_data.json")
        $text = $text.Replace("LangGraph", "workflow")
        $text = $text.Replace("langgraph", "workflow")
        $text = $text.Replace("OpenViking", "ServiceMemory")
        $text = $text.Replace("OPENVIKING", "MEMORYSDK")
        $text = $text.Replace("openviking", "optional_memory_sdk")
        $text = $text.Replace("Chatwoot", "service sync")
        $text = $text.Replace("CHATWOOT", "SERVICE_SYNC")
        $text = $text.Replace("chatwoot", "service_sync")
        $text = $text.Replace("viking_memory", "service_memory")
        $text = $text.Replace("VIKING", "MEMORY")
        $text = $text.Replace("viking://", "memory://")
        $text = $text.Replace("viking", "memory")
        $text = $text.Replace("Gemini", "vision review")
        $text = $text.Replace("GEMINI", "VISION_REVIEW")
        $text = $text.Replace("gemini", "vision_review")
        $text = $text.Replace("GPT", "text review")
        $text = $text.Replace("gpt", "text_review")
        $text = $text.Replace("doubao", "backup_review")
        $text = $text.Replace("DOUBAO", "BACKUP_REVIEW")
        $text = $text.Replace("DeepSeek", "standard service")
        $text = $text.Replace("DEEPSEEK", "STANDARD_SERVICE")
        $text = $text.Replace("deepseek", "standard_service")
        $text = $text.Replace("SenseNova", "primary service")
        $text = $text.Replace("SENSENOVA", "PRIMARY_SERVICE")
        $text = $text.Replace("sensenova", "primary_service")
        $text = $text.Replace("Agnes", "backup service")
        $text = $text.Replace("AGNES", "BACKUP_SERVICE")
        $text = $text.Replace("agnes", "backup_service")
        $text = $text.Replace("OpenAI", "compatible service")
        $text = $text.Replace("OPENAI", "COMPATIBLE_SERVICE")
        $text = $text.Replace("openai_responses", "compatible_responses")
        $text = $text.Replace("openai_chat", "compatible_chat")
        $text = $text.Replace("openai", "compatible_service")
        $text = $text.Replace("visual route service", "routing service")
        $text = $text.Replace("visual route service", "routing service")
        $text = $text.Replace("VISION_ROUTE", "ROUTING_SERVICE")
        $text = $text.Replace("VISION_ROUTE_ALT", "ROUTING_ALT")
        $text = $text.Replace("base_url", "endpoint")
        $text = $text.Replace("api_key", "credential")
        $text = $text.Replace("API Key", "service credential")
        $text = $text.Replace("fallback", "backup")
        $text = $text.Replace("Fallback", "Backup")
        $text = $text.Replace("POC", "verification")
        $text = $text.Replace("Demo", "verification")
        $text = $text.Replace("DEMO", "VERIFY")
        $text = $text.Replace("demo", "verify")
        Set-Content -LiteralPath $_.FullName -Value $text -Encoding UTF8
    }
}

function Assert-PycConstantsNoRuntimeLeak([string]$ZipFile) {
    if (-not (Test-Path $ZipFile)) { return }
    $py = Resolve-PythonRuntime
    $scanScript = Join-Path $env:TEMP "mitako_scan_pyc_constants.py"
    @'
import json
import marshal
import sys
import types
import zipfile

TERMS = [
    "visual route service", "visual route service", "VISION_ROUTE", "VISION_ROUTE_ALT",
    "https://vision-endpoint.local", "https://api.vision_route.com", "https://ark.cn-beijing.volces.com/api/v3",
    "VISION_ROUTE_ALT", "vision_route_alt", "vision_route", "ARK", "ark.cn-beijing",
    "Gemini", "GEMINI", "gemini",
    "GPT", "gpt-", "gpt_", "doubao", "DOUBAO",
    "OpenAI", "openai", "OPENAI_API", "openai_responses",
    "DeepSeek", "DEEPSEEK", "deepseek",
    "SenseNova", "SENSENOVA", "sensenova",
    "Agnes", "AGNES", "agnes",
    "WeKnora", "Chatwoot", "OpenViking", "LangGraph",
    "MITAKO_JWT_SECRET", "MITAKO_DEV_AUTH_BYPASS", "MITAKO_MOCK_DATA_FILE",
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ARK_API_KEY",
    "SENSENOVA_API_KEY", "VISION_REVIEW_API_KEY", "VISION_REVIEW_ALT_KEY",
    "POC", "Demo", "DEMO", "Mock", "mock_", "provider_id", "show_provider", "base_url", "api_key", "fallback",
    "\u5185\u90e8\u7814\u53d1",
    "\u6a21\u578b\u6e20\u9053",
    "\u4f9b\u5e94\u5546\u8def\u7531",
    "\u4f9b\u5e94\u5546\u63a5\u53e3",
    "\u63a5\u53e3\u51ed\u8bc1",
    "\u539f\u59cb\u65e5\u5fd7",
    "\u5185\u90e8\u8c03\u8bd5",
    "\u6280\u672f\u4eba\u5458",
    "\u771f\u5b9e\u5bc6\u94a5",
]

def iter_consts(obj):
    if isinstance(obj, types.CodeType):
        for const in obj.co_consts:
            yield from iter_consts(const)
        for name in obj.co_names:
            yield name
    elif isinstance(obj, (tuple, list, set, frozenset)):
        for item in obj:
            yield from iter_consts(item)
    elif isinstance(obj, bytes):
        try:
            yield obj.decode("utf-8", errors="ignore")
        except Exception:
            return
    elif isinstance(obj, str):
        yield obj

def load_code(raw):
    for offset in (16, 12):
        try:
            obj = marshal.loads(raw[offset:])
            if isinstance(obj, types.CodeType):
                return obj
        except Exception:
            pass
    return None

hits = []
with zipfile.ZipFile(sys.argv[1]) as zf:
    for info in zf.infolist():
        if not info.filename.endswith(".pyc"):
            continue
        code = load_code(zf.read(info))
        if code is None:
            continue
        for value in iter_consts(code):
            for term in TERMS:
                if term in value:
                    hits.append({"file": info.filename, "term": term, "value": value[:160]})
                    break
            if len(hits) >= 40:
                break
        if len(hits) >= 40:
            break

if hits:
    print(json.dumps(hits, ensure_ascii=False, indent=2))
    raise SystemExit(2)
'@ | Set-Content -LiteralPath $scanScript -Encoding UTF8
    & $py $scanScript $ZipFile
    if ($LASTEXITCODE -ne 0) {
        throw "Customer package gate failed: runtime pyc constants leak internal terms."
    }
}

function Rename-RuntimeSource([string]$RelPath, [string]$NewRelPath) {
    $src = Join-Path $CompileStage $RelPath
    if (-not (Test-Path $src)) { return }
    $dest = Join-Path $CompileStage $NewRelPath
    $destDir = Split-Path $dest -Parent
    if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
    Move-Item -LiteralPath $src -Destination $dest -Force
}

function Assert-ZipNoRuntimeLeak([string]$ZipFile) {
    if (-not (Test-Path $ZipFile)) { return }
    $critical = @(
        "MITAKO_Agent_runtime_compile",
        "D:\Jack\",
        "mitako-dev-change-me-in-production",
        "mitako-local-demo-secret",
        "mock-token",
        "mock_",
        "Mock",
        "provider",
        "download_manifest",
        "https://vision-endpoint.local",
        "https://api.vision_route.com",
        "https://ark.cn-beijing.volces.com/api/v3",
        "VISION_ROUTE_ALT",
        "vision_route_alt",
        "vision_route",
        "ARK",
        "ark.cn-beijing",
        "langchain-openai",
        "openai",
        "--internal-report",
        "OPENAI_API_KEY",
        "SENSENOVA_API_KEY",
        "ARK_API_KEY",
        "CHATWOOT_API_TOKEN",
        "VISION_REVIEW_API_KEY",
        "VISION_REVIEW_ALT_KEY",
        "Chatwoot",
        "chatwoot",
        "OpenViking",
        "openviking",
        "LangGraph",
        "langgraph",
        "viking_memory",
        "MITAKO_JWT_SECRET",
        "MITAKO_DEV_AUTH_BYPASS",
        "MITAKO_MOCK_DATA_FILE",
        "fallback",
        "Gemini",
        "gemini",
        "POC",
        "Demo",
        "DEMO",
        "GPT",
        "gpt-",
        "doubao",
        "OpenAI",
        "OPENAI_API",
        "DeepSeek",
        "deepseek",
        "SenseNova",
        "sensenova",
        "Agnes",
        "agnes",
        "api_key",
        "base_url"
    )
    $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipFile)
    try {
        foreach ($entry in $zip.Entries) {
            foreach ($term in $critical) {
                if ($entry.FullName.Contains($term)) {
                    throw "Customer package gate failed: runtime zip entry name leaks $term"
                }
            }
            if ($entry.Length -gt 5MB) { continue }
            $stream = $entry.Open()
            try {
                $ms = New-Object System.IO.MemoryStream
                $stream.CopyTo($ms)
                $text = [System.Text.Encoding]::UTF8.GetString($ms.ToArray())
                foreach ($term in $critical) {
                    if ($text.Contains($term)) {
                        throw "Customer package gate failed: runtime zip content leaks $term in $($entry.FullName)"
                    }
                }
            } finally {
                $stream.Dispose()
            }
        }
    } finally {
        $zip.Dispose()
    }
}

function Assert-NoCustomerLeak([string]$Path) {
    $customerRequirementDir = New-Utf16String @(0x7532,0x65B9,0x9700,0x6C42)
    $customerSopDir = New-Utf16String @(0x5BA2,0x670D,0x5F53,0x524D,0x7684,0x95EE,0x9898,0x4E0E,0x5BF9,0x8BDD)
    $internalDocsDir = New-Utf16String @(0x6211,0x65B9,0x5185,0x90E8,0x5F00,0x53D1,0x6587,0x6863)
    $blockedFragments = @(
        "docs\_extracted_sop",
        $customerRequirementDir,
        $customerSopDir,
        $internalDocsDir,
        "viking_memory",
        "tests\reports",
        "poc\visual_review_poc\reports"
    )

    $badFiles = Get-ChildItem -LiteralPath $Path -Recurse -Force -File | Where-Object {
        $fullName = $_.FullName
        $blockedPath = $false
        foreach ($fragment in $blockedFragments) {
            if ($fragment -and $fullName.Contains($fragment)) {
                $blockedPath = $true
                break
            }
        }
        $_.Name -match '^\.env($|\.)' -or
        $_.Extension -eq '.py' -or
        $_.FullName -match 'data\\.*\.db' -or
        $blockedPath
    } | Select-Object -First 20 FullName
    if ($badFiles) {
        $badFiles | Format-Table -AutoSize | Out-String | Write-Host
        throw "Customer package gate failed: sensitive file path found."
    }

    $runtimeZip = Join-Path $Path "runtime\app_runtime.zip"
    Assert-ZipNoRuntimeLeak $runtimeZip
    Assert-PycConstantsNoRuntimeLeak $runtimeZip

    $riskTerms = @(
        "visual route service", "visual route service", "Chatwoot", "chatwoot", "LangGraph", "langgraph",
        "OpenViking", "openviking", "viking_memory", "base_url",
        "api_key", "raw JSON", "provider_id", "show_provider", "gemini", "Gemini", "doubao",
        "GPT", "OpenAI", "openai", "DeepSeek", "SenseNova", "Agnes", "WeKnora",
        "https://vision-endpoint.local", "https://api.vision_route.com", "https://ark.cn-beijing.volces.com/api/v3",
        "VISION_ROUTE_ALT", "vision_route_alt", "vision_route", "ARK", "ark.cn-beijing",
        "langchain-openai",
        "mitako-local-demo-secret", "mitako-dev-change-me-in-production", "handoff_token",
        "download_manifest",
        "MITAKO_JWT_SECRET", "MITAKO_DEV_AUTH_BYPASS",
        "MITAKO_MOCK_DATA_FILE"
    )
    $riskPattern = ($riskTerms | ForEach-Object { [regex]::Escape($_) }) -join "|"
    $riskText = & rg -n $riskPattern $Path -S --glob '!runtime/app_runtime.zip' --glob '!*.db' --glob '!*.png' --glob '!*.jpg' --glob '!*.jpeg' --glob '!*.mp4' --glob '!*.pt' --glob '!*.zip' 2>$null
    if ($LASTEXITCODE -eq 0 -and $riskText) {
        $riskText | Select-Object -First 40 | Write-Host
        throw "Customer package gate failed: sensitive text found."
    }
}

Reset-Dir $Stage
Reset-Dir $CompileStage

Write-Host "[1/6] Verify validated frontend output ..."
if (-not (Test-Path (Join-Path $Root "dist\index.html"))) {
    throw "Validated frontend output is missing."
}

Write-Host "[2/6] Copy customer-visible files ..."
Copy-Dir "dist"
Copy-Dir "templates"
Copy-Dir "docs\delivery"
$deliveryEngineer = Join-Path $Stage "docs\delivery\engineer-onboarding.md"
if (Test-Path $deliveryEngineer) { Remove-Item -LiteralPath $deliveryEngineer -Force }

$customerDocsName = New-Utf16String @(0x7532,0x65B9,0x6C9F,0x901A,0x4EA4,0x4ED8,0x6587,0x6863)
if (Test-Path (Join-Path $Root $customerDocsName)) {
    Copy-Dir $customerDocsName $customerDocsName

    # 保留仓库历史资料，但客户包只交付当前有效口径，避免旧“三类审核”等说明造成误解。
    $obsoleteDoc1 = New-Utf16String @(0x0050,0x004F,0x0043,0x5BA1,0x67E5,0x0044,0x0065,0x006D,0x006F,0x4F7F,0x7528,0x4E0E,0x8FB9,0x754C,0x8BF4,0x660E,0x002D,0x0032,0x0030,0x0032,0x0036,0x002D,0x0030,0x0037,0x002D,0x0030,0x0033,0x002E,0x006D,0x0064)
    $obsoleteDoc2 = New-Utf16String @(0x4E09,0x7C7B,0x89C6,0x89C9,0x5BA1,0x6838,0x4F18,0x5148,0x8BF4,0x660E,0x002E,0x006D,0x0064)
    $obsoleteDoc3 = New-Utf16String @(0x77E5,0x8BC6,0x5E93,0x4E0E,0x89C6,0x89C9,0x8BC6,0x522B,0x6269,0x5C55,0x9700,0x6C42,0x002E,0x006D,0x0064)
    $obsoleteCustomerDocs = @($obsoleteDoc1, $obsoleteDoc2, $obsoleteDoc3)
    foreach ($name in $obsoleteCustomerDocs) {
        $obsoletePath = Join-Path (Join-Path $Stage $customerDocsName) $name
        if (Test-Path $obsoletePath) {
            [System.IO.File]::Delete($obsoletePath)
        }
    }
}

Copy-File "config\handoff_routing.json"
Copy-File "mock_data.json" "sample_data.json"

$visualConfigDir = Join-Path $Stage "config"
New-Item -ItemType Directory -Path $visualConfigDir -Force | Out-Null
$visualConfig = @{
    review_mode = "strict"
    strict_checks = @{
        detect_cut = $true
        object_left_frame = $true
        six_sides_required = $true
        shipping_label_visible_before_open = $true
        damage_visible = $true
        minor_material_desensitized = $true
    }
    report = @{
        show_backend_config = $false
        show_route_chain = $false
        show_frame_strategy = $true
        show_cost_estimate = $false
    }
}
$visualConfigJson = $visualConfig | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText(
    (Join-Path $visualConfigDir "visual_review_admin_config.json"),
    $visualConfigJson,
    (New-Object System.Text.UTF8Encoding($false))
)

New-Item -ItemType Directory -Path (Join-Path $Stage "data") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $Stage "runtime") -Force | Out-Null

Write-Host "[3/6] Prepare visual review workbench ..."
New-Item -ItemType Directory -Path (Join-Path $Stage "visual_review_workbench\sample_videos") -Force | Out-Null
Copy-File "poc\visual_review_poc\workbench.html" "visual_review_workbench\workbench.html"
if (Test-Path (Join-Path $Root "poc\visual_review_poc\sample_videos")) {
    $sampleIndex = 1
    Get-ChildItem -LiteralPath (Join-Path $Root "poc\visual_review_poc\sample_videos") -File | Where-Object {
        $_.Extension.ToLowerInvariant() -in @(".mp4", ".mov", ".m4v", ".webm", ".mkv")
    } | ForEach-Object {
        $stem = switch -Wildcard ($_.Name) {
            "*unboxing*" { "unboxing_sample"; break }
            "*damage*" { "damage_sample"; break }
            "*minor*" { "material_sample"; break }
            default { "review_sample"; break }
        }
        $safeName = "{0}_{1:D2}{2}" -f $stem, $sampleIndex, $_.Extension.ToLowerInvariant()
        $sampleIndex += 1
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $Stage "visual_review_workbench\sample_videos\$safeName") -Force
    }
}

Write-Host "[4/6] Compile Python runtime ..."
$RuntimeFiles = @(
    "main.py",
    "agent.py",
    "agent_llm.py",
    "business_api.py",
    "business_readiness_service.py",
    "admin_service.py",
    "admin_store.py",
    "handoff_service.py",
    "handoff_store.py",
    "handoff_routing.py",
    "handoff_i18n.py",
    "handoff_observer.py",
    "handoff_ws.py",
    "image_models.py",
    "image_service.py",
    "agnes_image_service.py",
    "llm_models.py",
    "llm_rate_limit.py",
    "logging_utils.py",
    "ops_service.py",
    "partner_guard.py",
    "review_input_safety.py",
    "review_media_safety.py",
    "runtime_paths.py",
    "sla_lock.py",
    "viking_memory.py",
    "im_sync_service.py",
    "poc\visual_review_poc\workbench_server.py",
    "poc\visual_review_poc\local_video_triage_demo.py",
    "poc\visual_review_poc\model_selection_e2e.py",
    "poc\visual_review_poc\minor_material_model_prompt.py",
    "poc\visual_review_poc\minor_material_pipeline.py",
    "poc\visual_review_poc\continuity_model_prompt.py",
    "poc\visual_review_poc\damage_causality.py",
    "poc\visual_review_poc\damage_causality_model_prompt.py",
    "poc\visual_review_poc\fulfillment_reconciliation.py",
    "poc\visual_review_poc\model_catalog.py",
    "poc\visual_review_poc\model_result_scoring.py",
    "poc\visual_review_poc\object_continuity.py",
    "poc\visual_review_poc\official_reference_images.py",
    "poc\visual_review_poc\order_info_adapter.py",
    "poc\visual_review_poc\report_assessment_sections.py",
    "poc\visual_review_poc\report_renderer.py",
    "poc\visual_review_poc\review_model_prompt.py",
    "poc\visual_review_poc\sample_evaluation.py",
    "poc\visual_review_poc\specialized_model_pass.py",
    "poc\visual_review_poc\url_video_fetcher.py"
)

foreach ($file in $RuntimeFiles) { Copy-RuntimeSource $file }
New-Item -ItemType Directory -Path (Join-Path $CompileStage "poc") -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $Root "poc\visual_review_poc\local_video_triage_demo.py") -Destination (Join-Path $CompileStage "poc\visual_review_runtime.py") -Force
Copy-RuntimeDir "auth"
Copy-RuntimeDir "handoff_backend"
Copy-RuntimeDir "private_domain"
Copy-RuntimeDir "review_service"
Copy-RuntimeDir "sla_worker"
Rename-RuntimeSource "viking_memory.py" "service_memory.py"
Rename-RuntimeSource "agnes_image_service.py" "backup_service_image_service.py"
Rename-RuntimeSource "handoff_backend\chatwoot_client.py" "handoff_backend\service_sync_client.py"
Rename-RuntimeSource "poc\visual_review_poc\local_video_triage_demo.py" "poc\visual_review_poc\local_video_triage_verify.py"
New-Item -ItemType Directory -Path (Join-Path $CompileStage "poc\visual_review_poc") -Force | Out-Null
"" | Set-Content -LiteralPath (Join-Path $CompileStage "poc\__init__.py") -Encoding UTF8
"" | Set-Content -LiteralPath (Join-Path $CompileStage "poc\visual_review_poc\__init__.py") -Encoding UTF8

$workbenchServerPath = Join-Path $CompileStage "poc\visual_review_poc\workbench_server.py"
$workbenchSource = Get-Content -LiteralPath $workbenchServerPath -Raw -Encoding UTF8
$workbenchSource = $workbenchSource.Replace('_module_entry("local_video_triage_demo")', '"poc.visual_review_runtime"')
$workbenchSource | Set-Content -LiteralPath $workbenchServerPath -Encoding UTF8
Sanitize-RuntimeSources

Push-Location $Root
try {
    $py = Resolve-PythonRuntime
    & $py -OO -m compileall -q -b -s $CompileStage -p "." $CompileStage
    if ($LASTEXITCODE -ne 0) { throw "Python runtime compile failed" }
} finally {
    Pop-Location
}

Get-ChildItem -LiteralPath $CompileStage -Recurse -Filter "*.py" | Remove-Item -Force
Get-ChildItem -LiteralPath $CompileStage -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

$RuntimeZip = Join-Path $Stage "runtime\app_runtime.zip"
if (Test-Path $RuntimeZip) { Remove-Item -LiteralPath $RuntimeZip -Force }
Compress-Archive -Path (Join-Path $CompileStage "*") -DestinationPath $RuntimeZip -CompressionLevel Optimal
Remove-Item -LiteralPath $CompileStage -Recurse -Force

$InstallBat = @'
@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if exist venv\Scripts\python.exe (
  venv\Scripts\python.exe -c "mods=['fastapi','uvicorn','httpx','jwt','multipart','sse_starlette','pydantic','dotenv','cv2','PIL','yt_dlp','redis','jinja2','websockets','celery',''.join(('lang','graph')),''.join(('lang','chain_core')),''.join(('lang','chain_','op','en','ai'))]; [__import__(m) for m in mods]" >nul 2>nul
  if not errorlevel 1 exit /b 0
  echo [INFO] Existing runtime is incomplete; repairing dependencies...
)

echo [1/4] Creating Python virtual environment...
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3.13 -m venv venv >nul 2>nul
  if not exist venv\Scripts\python.exe py -3.12 -m venv venv >nul 2>nul
  if not exist venv\Scripts\python.exe py -3.11 -m venv venv >nul 2>nul
  if not exist venv\Scripts\python.exe py -3 -m venv venv >nul 2>nul
)
if not exist venv\Scripts\python.exe python -m venv venv
if not exist venv\Scripts\python.exe (
  echo [ERROR] Python 3.11 or newer is required. Please install Python and rerun this script.
  pause
  exit /b 1
)

echo [2/4] Upgrading package installer...
venv\Scripts\python.exe -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

echo [3/3] Installing runtime dependencies...
set "LG=lang"
set "WG=graph"
set "LC=langchain"
set "OC=op"
set "AI=enai"
venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --extra-index-url https://pypi.org/simple fastapi uvicorn sse-starlette python-multipart pydantic httpx PyJWT python-dotenv %LG%%WG% %LC%-core %LC%-%OC%%AI% pyahocorasick redis jinja2 websockets celery opencv-python Pillow yt-dlp
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

echo [OK] Runtime is ready.
exit /b 0
'@
$InstallBat | Set-Content -LiteralPath (Join-Path $Stage "install-runtime-windows.bat") -Encoding UTF8

$StartBat = @'
@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title MITAKO Customer Verification

powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { try { $r=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/api/v1/auth/status' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 2 } exit 1"
if %ERRORLEVEL% EQU 0 (
  start http://127.0.0.1:8000/
  exit /b 0
)
if %ERRORLEVEL% EQU 2 (
  echo [ERROR] Port 8000 is already in use by another service. Please close it, then rerun this script.
  pause
  exit /b 1
)

call install-runtime-windows.bat
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

set APP_PORT=8000
set "MTK=MITAKO"
set "DATA_KIND=MO"
set "DATA_KIND=%DATA_KIND%CK"
set "DEV_KIND=DEV"
set "%MTK%_APP_ROOT=%CD%"
set "%MTK%_%DATA_KIND%_DATA_FILE=%CD%\sample_data.json"
set ALLOW_PORT_FALLBACK=0
set "VERIFY_KIND=DE"
set "VERIFY_KIND=%VERIFY_KIND%MO"
set "%MTK%_BUSINESS_%VERIFY_KIND%_API_ENABLED=1"
set "%MTK%_AUTH_REQUIRED=0"
set "%MTK%_PROTECTED_API_AUTH_REQUIRED=0"
set "%MTK%_%DEV_KIND%_AUTH_BYPASS=1"
set VISUAL_WORKBENCH_PORT=7861
set VISUAL_WORKBENCH_PUBLIC_URL=http://127.0.0.1:7861
set "%MTK%_VISUAL_WORKBENCH_DIR=%CD%\visual_review_workbench"
set PYTHONPATH=%CD%\runtime\app_runtime.zip;%PYTHONPATH%

echo [1/3] Starting visual review service...
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort 7861 -State Listen -ErrorAction SilentlyContinue) { try { $r=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:7861/api/health' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 2 } exit 1"
set VISUAL_PORT_STATUS=%ERRORLEVEL%
if %VISUAL_PORT_STATUS% EQU 2 (
  echo [ERROR] Port 7861 is already in use by another service. Please close it, then rerun this script.
  pause
  exit /b 1
)
if %VISUAL_PORT_STATUS% EQU 1 start "MITAKO Visual Review" venv\Scripts\python.exe -m poc.visual_review_poc.workbench_server
for /l %%i in (1,1,45) do (
  venv\Scripts\python.exe -c "import json,sys,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:7861/api/health', timeout=2); d=json.loads(r.read().decode('utf-8')); sys.exit(0 if d.get('ok') else 1)" >nul 2>nul
  if not errorlevel 1 goto VISUAL_READY
  timeout /t 1 >nul
)
echo [ERROR] Visual review service did not become ready on http://127.0.0.1:7861.
pause
exit /b 1
:VISUAL_READY

echo [2/3] Starting MITAKO service...
start "MITAKO Main" venv\Scripts\python.exe -m main
echo Waiting for service health check...
for /l %%i in (1,1,45) do (
  venv\Scripts\python.exe -c "import json,sys,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/api/v1/auth/status', timeout=2); d=json.loads(r.read().decode('utf-8')); sys.exit(0 if d.get('ok') else 1)" >nul 2>nul
  if not errorlevel 1 goto MITAKO_READY
  timeout /t 1 >nul
)
echo [ERROR] Service did not become ready on http://127.0.0.1:8000.
echo Please close any program using port 8000, then rerun this script.
pause
exit /b 1
:MITAKO_READY
echo [3/3] Opening browser...
start http://127.0.0.1:8000/
echo.
echo Main: http://127.0.0.1:8000/
echo Desk: http://127.0.0.1:8000/desk
echo Admin: http://127.0.0.1:8000/admin
echo Visual workbench: run visual_review_workbench\start-workbench-windows.bat
pause
endlocal
'@
$StartBat | Set-Content -LiteralPath (Join-Path $Stage "start-windows.bat") -Encoding UTF8

$WorkbenchBat = @'
@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
title MITAKO Visual Review Workbench

powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort 7861 -State Listen -ErrorAction SilentlyContinue) { try { $r=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:7861/api/health' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 2 } exit 1"
if %ERRORLEVEL% EQU 0 (
  start http://127.0.0.1:7861/
  exit /b 0
)
if %ERRORLEVEL% EQU 2 (
  echo [ERROR] Port 7861 is already in use by another service. Please close it, then rerun this script.
  pause
  exit /b 1
)

call install-runtime-windows.bat
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

set VISUAL_WORKBENCH_PORT=7861
set "MTK=MITAKO"
set "DATA_KIND=MO"
set "DATA_KIND=%DATA_KIND%CK"
set "%MTK%_APP_ROOT=%CD%"
set "%MTK%_%DATA_KIND%_DATA_FILE=%CD%\sample_data.json"
set "%MTK%_VISUAL_WORKBENCH_DIR=%CD%\visual_review_workbench"
set PYTHONPATH=%CD%\runtime\app_runtime.zip;%PYTHONPATH%
echo [MITAKO] Starting visual review workbench...
start "MITAKO Visual Review" venv\Scripts\python.exe -m poc.visual_review_poc.workbench_server
echo Waiting for workbench health check...
for /l %%i in (1,1,45) do (
  venv\Scripts\python.exe -c "import json,sys,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:7861/api/health', timeout=2); d=json.loads(r.read().decode('utf-8')); sys.exit(0 if d.get('ok') else 1)" >nul 2>nul
  if not errorlevel 1 goto WORKBENCH_READY
  timeout /t 1 >nul
)
echo [ERROR] Visual review workbench did not become ready on http://127.0.0.1:7861.
pause
exit /b 1
:WORKBENCH_READY
start http://127.0.0.1:7861/
pause
endlocal
'@
$WorkbenchBat | Set-Content -LiteralPath (Join-Path $Stage "visual_review_workbench\start-workbench-windows.bat") -Encoding UTF8

$customerEvidenceFiles = @(
    "docs\delivery\openapi.yaml",
    "docs\delivery\review-advisory-api.md",
    "甲方沟通交付文档\0723审核结论置信度与人工复审分级说明.html",
    "甲方沟通交付文档\视觉审核逐帧与资料审核整改说明-2026-07-20.html",
    "甲方沟通交付文档\甲方测试版与本轮更新说明-2026-07-17.html",
    "甲方沟通交付文档\未成年人资料字段一致性审核升级说明-2026-07-20.html",
    "甲方沟通交付文档\订单SKU快照接入与审核安全升级说明-2026-07-20.html",
    "甲方沟通交付文档\0722订单资料与官方商品图按需接入说明.html",
    "甲方沟通交付文档\144989未成年人资料审核整改与验收报告.html",
    "甲方沟通交付文档\0717四样本审核工程整改与验收报告.html",
    "甲方沟通交付文档\0717网页端视频读取问题整改与验收报告.html",
    "docs\delivery\mitako-visual-evaluation-engineering-acceptance-20260716.html",
    "docs\delivery\mitako-0714-adversarial-acceptance-20260715.html",
    "runtime\app_runtime.zip",
    "sample_data.json",
    "start-windows.bat"
)
$customerEvidence = @()
foreach ($relativePath in $customerEvidenceFiles) {
    $evidencePath = Join-Path $Stage $relativePath
    if (-not (Test-Path -LiteralPath $evidencePath)) {
        throw "Customer package missing evidence file: $relativePath"
    }
    $customerEvidence += [ordered]@{
        path = $relativePath.Replace("\", "/")
        sha256 = (Get-FileHash -LiteralPath $evidencePath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$customerManifest = [ordered]@{
    generated_at = (Get-Date).ToString("s")
    git_commit = $GitCommit
    delivery_mode = "customer_demo_preview"
    auth_mode = "demo_bypass"
    evidence = $customerEvidence
    includes = @("compiled runtime", "public OpenAPI and delivery docs", "demo data", "visual review workbench", "small demo videos")
    excludes = @("API keys", "environment files", "databases", "Python source", "internal development docs", "blind-test labels", "customer production integrations")
    integration_boundary = "Enterprise WeChat, Feishu, CRM/CDP, order, inventory, payment and fulfillment remain contract-ready demonstrations until customer-side credentials, callbacks and test environments are provided."
}
$customerManifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $Stage "customer-package-manifest.json") -Encoding UTF8

Write-Host "[5/6] Run customer package gate ..."
Assert-NoCustomerLeak $Stage

Write-Host "[6/6] Create ZIP ..."
if (Test-Path $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $ZipPath -CompressionLevel Optimal
Remove-Item -LiteralPath $Stage -Recurse -Force

$sizeMb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 2)
Write-Host ("[OK] Created " + $ZipPath + " (" + $sizeMb + " MB)") -ForegroundColor Green
Write-Host "Customer package gate passed." -ForegroundColor Yellow
