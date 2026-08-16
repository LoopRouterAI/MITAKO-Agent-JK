$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function U([int[]]$Codes) {
    return -join ($Codes | ForEach-Object { [char]$_ })
}

$TextTitle = U @(23458,26381,32,65,103,101,110,116,32,33853,22320,39564,25910,38376,31105)
$TextPass = U @(36890,36807)
$TextFail = U @(22833,36133)
$TextReport = U @(25253,21578,24050,29983,25104)
$TextRiskPass = U @(26410,21457,29616,26087,31216,21628,38169,35823,35805,26415)
$TextRiskFail = U @(21457,29616,26087,31216,25110,38169,35823,35805,26415)
$ReportTitle = U @(23458,26381,32,65,103,101,110,116,32,33853,22320,39564,25910,25253,21578)
$ReportTime = U @(26102,38388)
$ReportResult = U @(32467,26524)
$ReportScope = U @(33539,22260)
$ReportScopeText = U @(20154,26684,47,77,66,84,73,12289,83,79,80,12289,19977,22823,23457,26680,12289,83,83,69,32,33073,25935,12289,21069,31471,26500,24314,12289,23458,25143,21487,35265,39118,38505,25195,25551)
$ReportGate = U @(38376,31105)
$ReportStatus = U @(32467,26524)
$ReportNote = U @(35828,26126)
$ReportRetry = U @(22833,36133,22788,29702,65306,20462,22797,22833,36133,39033,21518,24517,39035,37325,26032,36816,34892)

$ReportDir = Join-Path $Root "tests\reports"
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Report = Join-Path $ReportDir "cs_agent_acceptance_$Stamp.md"
$Py = Join-Path $Root "venv\Scripts\python.exe"
$Fail = $false
$Results = @()

function Add-Result([string]$Name, [string]$Status, [string]$Note) {
    $script:Results += "| $Name | $Status | $Note |"
}

function Invoke-Gate([string]$Name, [scriptblock]$Block) {
    Write-Host ""
    Write-Host "[$Name]" -ForegroundColor Cyan
    & $Block
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[$TextFail] $Name" -ForegroundColor Red
        Add-Result $Name "FAIL" "exit code $LASTEXITCODE"
        $script:Fail = $true
    } else {
        Write-Host "[$TextPass] $Name" -ForegroundColor Green
        Add-Result $Name "PASS" $TextPass
    }
}

Write-Host "=== MITAKO $TextTitle ===" -ForegroundColor Yellow

if (-not (Test-Path $Py)) {
    Add-Result "Python venv" "FAIL" "venv\Scripts\python.exe not found"
    $Fail = $true
} else {
    Add-Result "Python venv" "PASS" "found"
}

if (-not $Fail) {
    Invoke-Gate "Python py_compile" {
        & $Py -m py_compile agent.py business_readiness_service.py main.py tests\e2e\run_mock_business_guard_e2e.py
    }
    Invoke-Gate "CS Agent business E2E" {
        & $Py tests\e2e\run_mock_business_guard_e2e.py
    }
}

Invoke-Gate "Frontend production build" {
    npm run build
}

Write-Host ""
Write-Host "[Public text risk scan]" -ForegroundColor Cyan
$ScanPattern = @(
    (U @(34430,39290)),
    (U @(34430,28120)),
    (U @(25105,26159,34430,39290)),
    (U @(26381,21153,26723,20301)),
    (U @(24403,21069,26368,38656,35201,36319,36827)),
    (U @(24744,30340,35746,21333,36824,22312,22788,29702)),
    (U @(77,73,84,65,75,79,34430,28120))
) -join "|"
$ScanOutput = & rg -n $ScanPattern agent.py business_readiness_service.py main.py src 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host $ScanOutput -ForegroundColor Red
    Add-Result "Public text risk scan" "FAIL" $TextRiskFail
    $Fail = $true
} else {
    Write-Host "[$TextPass] $TextRiskPass" -ForegroundColor Green
    Add-Result "Public text risk scan" "PASS" $TextRiskPass
}

$StatusText = if ($Fail) { "FAIL" } else { "PASS" }
$Now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$Lines = @(
    "# $ReportTitle",
    "",
    "- ${ReportTime}: $Now",
    "- ${ReportResult}: $StatusText",
    "- ${ReportScope}: $ReportScopeText",
    "",
    "| $ReportGate | $ReportStatus | $ReportNote |",
    "| --- | --- | --- |"
) + $Results + @(
    "",
    "$ReportRetry ``scripts\run_cs_agent_acceptance.ps1``."
)
$Lines | Set-Content -LiteralPath $Report -Encoding UTF8

Write-Host ""
Write-Host "${TextReport}: $Report" -ForegroundColor Yellow

if ($Fail) {
    exit 1
}
exit 0
