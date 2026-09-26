# Spending Agent Test Runner
# ===========================
# Comprehensive test suite for Spending Agent implementation
# 
# Usage:
#   .\scripts\test-spending-agent.ps1 [-TestSuite <all|unit|integration|e2e|performance>]
#
# Examples:
#   .\scripts\test-spending-agent.ps1                    # Run all tests
#   .\scripts\test-spending-agent.ps1 -TestSuite unit    # Run only unit tests
#   .\scripts\test-spending-agent.ps1 -TestSuite e2e     # Run only E2E tests

param(
    [ValidateSet("all", "unit", "integration", "e2e", "performance")]
    [string]$TestSuite = "all"
)

$ErrorActionPreference = "Stop"
$RootPath = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Spending Agent Test Suite" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Track test results
$TestResults = @{
    Total = 0
    Passed = 0
    Failed = 0
    Skipped = 0
}

function Run-Tests {
    param(
        [string]$Path,
        [string]$Name,
        [string[]]$AdditionalArgs = @()
    )
    
    Write-Host "Running $Name tests..." -ForegroundColor Yellow
    Write-Host "Path: $Path" -ForegroundColor Gray
    Write-Host ""
    
    $pytestArgs = @(
        $Path,
        "-v",
        "--tb=short"
    ) + $AdditionalArgs
    
    $startTime = Get-Date
    $exitCode = 0
    
    try {
        & pytest @pytestArgs
        $exitCode = $LASTEXITCODE
    } catch {
        $exitCode = 1
    }
    
    $endTime = Get-Date
    $duration = $endTime - $startTime
    
    Write-Host ""
    Write-Host "Duration: $($duration.TotalSeconds.ToString("N2"))s" -ForegroundColor Gray
    Write-Host ""
    
    return $exitCode
}

# Run AI Service Unit Tests
if ($TestSuite -eq "all" -or $TestSuite -eq "unit") {
    Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "Task 1-3: Statistical Analysis Unit Tests" -ForegroundColor Cyan
    Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""
    
    $exitCode = Run-Tests `
        -Path "$RootPath\apps\ai-service\tests\test_spending_analyzer.py" `
        -Name "Statistical Analysis"
    
    if ($exitCode -eq 0) {
        $TestResults.Passed++
    } else {
        $TestResults.Failed++
        Write-Host "❌ Unit tests failed" -ForegroundColor Red
        if ($TestSuite -eq "unit") { exit 1 }
    }
    Write-Host ""
}

# Run AI Service Integration Tests
if ($TestSuite -eq "all" -or $TestSuite -eq "integration") {
    Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "Task 12: Spending Agent Integration Tests" -ForegroundColor Cyan
    Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""
    
    $exitCode = Run-Tests `
        -Path "$RootPath\apps\ai-service\tests\test_spending_integration.py" `
        -Name "Integration" `
        -AdditionalArgs @("-m", "not e2e")
    
    if ($exitCode -eq 0) {
        $TestResults.Passed++
    } else {
        $TestResults.Failed++
        Write-Host "❌ Integration tests failed" -ForegroundColor Red
        if ($TestSuite -eq "integration") { exit 1 }
    }
    Write-Host ""
}

# Run Backend E2E Tests
if ($TestSuite -eq "all" -or $TestSuite -eq "e2e") {
    Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "Task 13: End-to-End Tests" -ForegroundColor Cyan
    Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "⚠️  Requires backend to be running on http://localhost:8080" -ForegroundColor Yellow
    Write-Host ""
    
    $exitCode = Run-Tests `
        -Path "$RootPath\apps\backend\tests\e2e\test_spending_insights_e2e.py" `
        -Name "E2E" `
        -AdditionalArgs @("-m", "e2e")
    
    if ($exitCode -eq 0) {
        $TestResults.Passed++
    } else {
        $TestResults.Failed++
        Write-Host "❌ E2E tests failed" -ForegroundColor Red
        if ($TestSuite -eq "e2e") { exit 1 }
    }
    Write-Host ""
}

# Run Performance Tests
if ($TestSuite -eq "all" -or $TestSuite -eq "performance") {
    Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "Task 14: Performance Validation Tests" -ForegroundColor Cyan
    Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "⚠️  Requires backend to be running" -ForegroundColor Yellow
    Write-Host ""
    
    $exitCode = Run-Tests `
        -Path "$RootPath\apps\backend\tests\performance\test_spending_performance.py" `
        -Name "Performance" `
        -AdditionalArgs @("-m", "performance")
    
    if ($exitCode -eq 0) {
        $TestResults.Passed++
    } else {
        $TestResults.Failed++
        Write-Host "❌ Performance tests failed" -ForegroundColor Red
        if ($TestSuite -eq "performance") { exit 1 }
    }
    Write-Host ""
}

# Summary
Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "Test Summary" -ForegroundColor Cyan
Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "Test Suites Passed: $($TestResults.Passed)" -ForegroundColor Green
Write-Host "Test Suites Failed: $($TestResults.Failed)" -ForegroundColor Red
Write-Host ""

if ($TestResults.Failed -gt 0) {
    Write-Host "❌ Some tests failed. Review output above." -ForegroundColor Red
    exit 1
} else {
    Write-Host "✅ All test suites passed!" -ForegroundColor Green
    exit 0
}
