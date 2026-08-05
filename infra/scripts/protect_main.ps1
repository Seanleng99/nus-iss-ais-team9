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
            "CodeQL (python)"
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

$body | & $Gh api --method PUT "repos/$Repository/branches/main/protection" --input -
if ($LASTEXITCODE -ne 0) {
    throw "Branch protection could not be enabled. Check the repository plan and administrator permissions."
}

Write-Host "Protected main with pull-request review and required CI checks."
