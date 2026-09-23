# Add Test Transactions Script
# =============================
# Adds 6 months of test transaction data to test spending insights
#
# Usage: .\scripts\add-test-transactions.ps1 -UserId <your-user-id>

param(
    [Parameter(Mandatory=$true)]
    [string]$UserId,
    
    [string]$BackendUrl = "http://localhost:8080",
    [string]$ApiKey = "change-me-locally"
)

# Test data: 6 months of spending with clear patterns and anomalies
$transactions = @(
    # Month 1 (6 months ago) - Baseline
    @{description="Grocery shopping"; category="food"; amount=150.0; occurred_on=(Get-Date).AddMonths(-5).ToString("yyyy-MM-01"); recurring=$false},
    @{description="Restaurant dinner"; category="dining"; amount=80.0; occurred_on=(Get-Date).AddMonths(-5).ToString("yyyy-MM-05"); recurring=$false},
    @{description="Bus fare"; category="transport"; amount=50.0; occurred_on=(Get-Date).AddMonths(-5).ToString("yyyy-MM-10"); recurring=$false},
    @{description="Netflix subscription"; category="entertainment"; amount=15.0; occurred_on=(Get-Date).AddMonths(-5).ToString("yyyy-MM-15"); recurring=$true},
    @{description="Electric bill"; category="utilities"; amount=120.0; occurred_on=(Get-Date).AddMonths(-5).ToString("yyyy-MM-20"); recurring=$true},
    
    # Month 2 (5 months ago) - Slight increase
    @{description="Grocery shopping"; category="food"; amount=160.0; occurred_on=(Get-Date).AddMonths(-4).ToString("yyyy-MM-01"); recurring=$false},
    @{description="Restaurant dinner"; category="dining"; amount=85.0; occurred_on=(Get-Date).AddMonths(-4).ToString("yyyy-MM-05"); recurring=$false},
    @{description="Bus fare"; category="transport"; amount=50.0; occurred_on=(Get-Date).AddMonths(-4).ToString("yyyy-MM-10"); recurring=$false},
    @{description="Movie tickets"; category="entertainment"; amount=30.0; occurred_on=(Get-Date).AddMonths(-4).ToString("yyyy-MM-15"); recurring=$false},
    @{description="Electric bill"; category="utilities"; amount=125.0; occurred_on=(Get-Date).AddMonths(-4).ToString("yyyy-MM-20"); recurring=$true},
    
    # Month 3 (4 months ago) - Continued trend
    @{description="Grocery shopping"; category="food"; amount=180.0; occurred_on=(Get-Date).AddMonths(-3).ToString("yyyy-MM-01"); recurring=$false},
    @{description="Restaurant dinner"; category="dining"; amount=90.0; occurred_on=(Get-Date).AddMonths(-3).ToString("yyyy-MM-05"); recurring=$false},
    @{description="Bus fare"; category="transport"; amount=55.0; occurred_on=(Get-Date).AddMonths(-3).ToString("yyyy-MM-10"); recurring=$false},
    @{description="Netflix subscription"; category="entertainment"; amount=15.0; occurred_on=(Get-Date).AddMonths(-3).ToString("yyyy-MM-15"); recurring=$true},
    @{description="Electric bill"; category="utilities"; amount=130.0; occurred_on=(Get-Date).AddMonths(-3).ToString("yyyy-MM-20"); recurring=$true},
    
    # Month 4 (3 months ago) - Higher spending
    @{description="Grocery shopping"; category="food"; amount=200.0; occurred_on=(Get-Date).AddMonths(-2).ToString("yyyy-MM-01"); recurring=$false},
    @{description="Restaurant dinner"; category="dining"; amount=95.0; occurred_on=(Get-Date).AddMonths(-2).ToString("yyyy-MM-05"); recurring=$false},
    @{description="Bus fare"; category="transport"; amount=55.0; occurred_on=(Get-Date).AddMonths(-2).ToString("yyyy-MM-10"); recurring=$false},
    @{description="Concert tickets"; category="entertainment"; amount=100.0; occurred_on=(Get-Date).AddMonths(-2).ToString("yyyy-MM-15"); recurring=$false},
    @{description="Electric bill"; category="utilities"; amount=135.0; occurred_on=(Get-Date).AddMonths(-2).ToString("yyyy-MM-20"); recurring=$true},
    
    # Month 5 (2 months ago) - ANOMALY MONTH (spike in dining)
    @{description="Grocery shopping"; category="food"; amount=220.0; occurred_on=(Get-Date).AddMonths(-1).ToString("yyyy-MM-01"); recurring=$false},
    @{description="Fancy restaurant"; category="dining"; amount=450.0; occurred_on=(Get-Date).AddMonths(-1).ToString("yyyy-MM-05"); recurring=$false},  # ANOMALY!
    @{description="Bus fare"; category="transport"; amount=60.0; occurred_on=(Get-Date).AddMonths(-1).ToString("yyyy-MM-10"); recurring=$false},
    @{description="Netflix subscription"; category="entertainment"; amount=15.0; occurred_on=(Get-Date).AddMonths(-1).ToString("yyyy-MM-15"); recurring=$true},
    @{description="Electric bill"; category="utilities"; amount=140.0; occurred_on=(Get-Date).AddMonths(-1).ToString("yyyy-MM-20"); recurring=$true},
    @{description="Weekend getaway"; category="entertainment"; amount=300.0; occurred_on=(Get-Date).AddMonths(-1).ToString("yyyy-MM-25"); recurring=$false},  # ANOMALY!
    
    # Month 6 (Current month) - Normal spending
    @{description="Grocery shopping"; category="food"; amount=230.0; occurred_on=(Get-Date).ToString("yyyy-MM-01"); recurring=$false},
    @{description="Restaurant dinner"; category="dining"; amount=100.0; occurred_on=(Get-Date).ToString("yyyy-MM-05"); recurring=$false},
    @{description="Bus fare"; category="transport"; amount=60.0; occurred_on=(Get-Date).ToString("yyyy-MM-10"); recurring=$false},
    @{description="Netflix subscription"; category="entertainment"; amount=15.0; occurred_on=(Get-Date).ToString("yyyy-MM-15"); recurring=$true},
    @{description="Electric bill"; category="utilities"; amount=145.0; occurred_on=(Get-Date).ToString("yyyy-MM-20"); recurring=$true}
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Adding Test Transactions" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "User ID: $UserId"
Write-Host "Backend URL: $BackendUrl"
Write-Host "Transactions to add: $($transactions.Count)"
Write-Host ""

$successCount = 0
$failCount = 0

foreach ($txn in $transactions) {
    $body = @{
        description = $txn.description
        category = $txn.category
        amount = @{
            currency = "SGD"
            amount = $txn.amount
        }
        occurred_on = $txn.occurred_on
        recurring = $txn.recurring
    } | ConvertTo-Json -Depth 3
    
    try {
        $response = Invoke-RestMethod -Uri "$BackendUrl/users/$UserId/transactions" `
            -Method POST `
            -Headers @{
                "Content-Type" = "application/json"
                "X-API-Key" = $ApiKey
            } `
            -Body $body
        
        Write-Host "✓ Added: $($txn.description) - SGD $($txn.amount) on $($txn.occurred_on)" -ForegroundColor Green
        $successCount++
    }
    catch {
        Write-Host "✗ Failed: $($txn.description) - $($_.Exception.Message)" -ForegroundColor Red
        $failCount++
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Successful: $successCount" -ForegroundColor Green
Write-Host "Failed: $failCount" -ForegroundColor Red
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Go to Overview dashboard to see spending insights" -ForegroundColor Yellow
Write-Host "2. Ask the Coach: 'Review my spending patterns'" -ForegroundColor Yellow
Write-Host ""
