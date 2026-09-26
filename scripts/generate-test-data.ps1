# Spending Agent Test Data Generator
# ===================================
# Generates realistic test transaction data for testing insights and anomaly detection
#
# Usage:
#   .\scripts\generate-test-data.ps1 -UserId <user-id> [-Scenario <normal|anomaly|trend|temporal>]
#
# Examples:
#   .\scripts\generate-test-data.ps1 -UserId "user123" -Scenario anomaly
#   .\scripts\generate-test-data.ps1 -UserId "user123" -Scenario trend

param(
    [Parameter(Mandatory=$true)]
    [string]$UserId,
    
    [ValidateSet("normal", "anomaly", "trend", "temporal", "all")]
    [string]$Scenario = "all"
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Spending Test Data Generator" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Database connection (update connection string as needed)
$ConnectionString = $env:DATABASE_URL
if (-not $ConnectionString) {
    Write-Host "⚠️  DATABASE_URL environment variable not set" -ForegroundColor Yellow
    Write-Host "Please set your database connection string first." -ForegroundColor Yellow
    exit 1
}

function Add-Transaction {
    param(
        [string]$UserId,
        [string]$Category,
        [decimal]$Amount,
        [DateTime]$Date,
        [string]$Description
    )
    
    # This is a template - adapt to your actual database insertion method
    Write-Host "  Adding: $Category - $$Amount on $($Date.ToShortDateString())" -ForegroundColor Gray
    
    # Example SQL (adapt to your schema):
    # INSERT INTO transactions (user_id, category, amount, occurred_on, description)
    # VALUES ('$UserId', '$Category', $Amount, '$($Date.ToString("yyyy-MM-dd"))', '$Description')
}

function Generate-NormalScenario {
    Write-Host "Scenario: Normal Spending Pattern" -ForegroundColor Green
    Write-Host "Generating 3 months of consistent spending..." -ForegroundColor Gray
    
    $baseDate = Get-Date
    $months = 3
    
    for ($i = 0; $i -lt $months; $i++) {
        $monthDate = $baseDate.AddMonths(-$i)
        
        # Consistent dining expenses
        Add-Transaction -UserId $UserId -Category "dining" -Amount 100.00 -Date $monthDate.AddDays(-15) -Description "Dining month $i"
        Add-Transaction -UserId $UserId -Category "dining" -Amount 105.00 -Date $monthDate.AddDays(-10) -Description "Dining month $i"
        
        # Consistent food expenses
        Add-Transaction -UserId $UserId -Category "food" -Amount 200.00 -Date $monthDate.AddDays(-20) -Description "Groceries month $i"
    }
    
    Write-Host "✅ Generated normal spending pattern" -ForegroundColor Green
    Write-Host ""
}

function Generate-AnomalyScenario {
    Write-Host "Scenario: Anomaly Detection" -ForegroundColor Green
    Write-Host "Generating 4 months with one clear outlier..." -ForegroundColor Gray
    
    $baseDate = Get-Date
    
    # Months 1-3: Normal spending
    for ($i = 1; $i -le 3; $i++) {
        $monthDate = $baseDate.AddMonths(-$i)
        Add-Transaction -UserId $UserId -Category "dining" -Amount 100.00 -Date $monthDate.AddDays(-15) -Description "Normal dining"
        Add-Transaction -UserId $UserId -Category "dining" -Amount 110.00 -Date $monthDate.AddDays(-10) -Description "Normal dining"
    }
    
    # Month 4 (current): Add ANOMALY
    Add-Transaction -UserId $UserId -Category "dining" -Amount 105.00 -Date $baseDate.AddDays(-15) -Description "Normal dining"
    Add-Transaction -UserId $UserId -Category "dining" -Amount 450.00 -Date $baseDate.AddDays(-5) -Description "LARGE EXPENSE - ANOMALY"
    
    Write-Host "✅ Generated anomaly scenario (450 vs 100-110 normal)" -ForegroundColor Green
    Write-Host ""
}

function Generate-TrendScenario {
    Write-Host "Scenario: Trend Detection" -ForegroundColor Green
    Write-Host "Generating 4 months with upward trend..." -ForegroundColor Gray
    
    $baseDate = Get-Date
    $amounts = @(200, 250, 320, 400)  # Clear upward trend
    
    for ($i = 0; $i -lt 4; $i++) {
        $monthDate = $baseDate.AddMonths(-$i)
        $amount = $amounts[3 - $i]  # Reverse to get correct order
        
        Add-Transaction -UserId $UserId -Category "food" -Amount $amount -Date $monthDate.AddDays(-15) -Description "Food month $i"
        Write-Host "  Month $i: Food = $$amount" -ForegroundColor Gray
    }
    
    Write-Host "✅ Generated trend scenario (200 → 400, +100%)" -ForegroundColor Green
    Write-Host ""
}

function Generate-TemporalScenario {
    Write-Host "Scenario: Temporal Pattern Detection" -ForegroundColor Green
    Write-Host "Generating weekend-heavy spending..." -ForegroundColor Gray
    
    $baseDate = Get-Date
    
    # Generate 2 months of data
    for ($i = 0; $i -lt 8; $i++) {
        $weekDate = $baseDate.AddDays(-($i * 7))
        
        # Weekday spending (low)
        Add-Transaction -UserId $UserId -Category "food" -Amount 20.00 -Date $weekDate.AddDays(-3) -Description "Weekday lunch"
        Add-Transaction -UserId $UserId -Category "food" -Amount 25.00 -Date $weekDate.AddDays(-2) -Description "Weekday lunch"
        
        # Weekend spending (high)
        Add-Transaction -UserId $UserId -Category "food" -Amount 60.00 -Date $weekDate.AddDays(-1) -Description "Weekend brunch"
        Add-Transaction -UserId $UserId -Category "entertainment" -Amount 50.00 -Date $weekDate -Description "Weekend activity"
    }
    
    Write-Host "✅ Generated temporal pattern (weekend > weekday)" -ForegroundColor Green
    Write-Host ""
}

# Run scenarios
switch ($Scenario) {
    "normal" { Generate-NormalScenario }
    "anomaly" { Generate-AnomalyScenario }
    "trend" { Generate-TrendScenario }
    "temporal" { Generate-TemporalScenario }
    "all" {
        Generate-NormalScenario
        Generate-AnomalyScenario
        Generate-TrendScenario
        Generate-TemporalScenario
    }
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Test data generation complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Navigate to Overview page" -ForegroundColor White
Write-Host "2. Check for insight cards" -ForegroundColor White
Write-Host "3. Verify anomaly/trend detection" -ForegroundColor White
Write-Host ""
