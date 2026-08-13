param([string]$Repository = "Seanleng99/nus-iss-ais-team9")

$ErrorActionPreference = "Stop"
$Gh = "C:\Program Files\GitHub CLI\gh.exe"
$body = @{
    required_status_checks = @{
        strict = $true
        contexts = @(
            "FastAPI tests and AI evals",
            "Streamlit tests",
            "Backend tests",
            "CloudFormation and Compose validation",
            "Backend to AI integration and load smoke",
            "Build hardened containers",
            "Python SAST (Bandit)"
        )
    }
    enforce_admins = $false
    required_pull_request_reviews = @{
        dismiss_stale_reviews = $true
        require_code_owner_reviews = $false
        required_approving_review_count = 1
    }
    restrictions = $null
    required_conversation_resolution = $true
    allow_force_pushes = $false
    allow_deletions = $false
} | ConvertTo-Json -Depth 6

$result = $body | & $Gh api --method PUT "repos/$Repository/branches/main/protection" --input - 2>&1
if ($LASTEXITCODE -ne 0) {
    if ($result -match "Upgrade to GitHub Pro or make this repository public") {
        Write-Warning "Branch protection is unavailable for this private repository on the current GitHub plan. Upgrade to GitHub Pro or make the repository public to enforce it."
        return
    }
    throw "Branch protection could not be enabled. Check the repository plan and administrator permissions."
}

$result
Write-Host "Protected main with pull-request review and required CI checks."
