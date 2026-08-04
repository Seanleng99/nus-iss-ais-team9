param(
    [string]$Repository = "Seanleng99/nus-iss-ais-team9",
    [string]$Region = "ap-southeast-1",
    [string]$FoundationStack = "ai-financial-wellness-coach-foundation",
    [string]$ApplicationStack = "ai-financial-wellness-coach-application",
    [string]$OidcStack = "ai-financial-wellness-coach-github-oidc"
)

$ErrorActionPreference = "Stop"
$Aws = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
$Gh = "C:\Program Files\GitHub CLI\gh.exe"

function Invoke-Aws {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $Aws @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "AWS CLI command failed: aws $($Arguments -join ' ')"
    }
}

function Invoke-Gh {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $Gh @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub CLI command failed: gh $($Arguments -join ' ')"
    }
}

function Get-StackOutputs {
    param([string]$StackName)
    $json = Invoke-Aws cloudformation describe-stacks `
        --stack-name $StackName `
        --region $Region `
        --query "Stacks[0].Outputs" `
        --output json
    $outputs = @{}
    foreach ($item in ($json | ConvertFrom-Json)) {
        $outputs[$item.OutputKey] = $item.OutputValue
    }
    return $outputs
}

Invoke-Gh auth status
$viewerRecord = Invoke-Gh api user | ConvertFrom-Json
$viewer = $viewerRecord.login
if ($viewer -ne $Repository.Split("/")[0]) {
    throw "GitHub CLI is authenticated as $viewer, not $($Repository.Split('/')[0])."
}

$foundation = Get-StackOutputs $FoundationStack
$application = Get-StackOutputs $ApplicationStack
$oidc = Get-StackOutputs $OidcStack
$baseUrl = "http://$($foundation.LoadBalancerDnsName)"

$oidcBody = @{ use_default = $true } | ConvertTo-Json -Compress
$oidcBody | & $Gh api --method PUT "repos/$Repository/actions/oidc/customization/sub" --input -
if ($LASTEXITCODE -ne 0) {
    throw "Could not enforce the default GitHub OIDC subject format."
}

$environmentBody = @{
    wait_timer = 0
    prevent_self_review = $false
    reviewers = @(
        @{
            type = "User"
            id = [int64]$viewerRecord.id
        }
    )
    deployment_branch_policy = @{
        protected_branches = $false
        custom_branch_policies = $true
    }
} | ConvertTo-Json -Depth 5
$environmentBody | & $Gh api --method PUT "repos/$Repository/environments/demo" --input -
if ($LASTEXITCODE -ne 0) {
    throw "Could not create the GitHub demo environment."
}

$branchPolicies = Invoke-Gh api "repos/$Repository/environments/demo/deployment-branch-policies"
$hasMainPolicy = ($branchPolicies | ConvertFrom-Json).branch_policies.name -contains "main"
if (-not $hasMainPolicy) {
    Invoke-Gh api --method POST `
        "repos/$Repository/environments/demo/deployment-branch-policies" `
        -f name=main `
        -f type=branch | Out-Null
}

$variables = [ordered]@{
    AWS_REGION = $Region
    AWS_PUBLISH_ROLE_ARN = $oidc.PublishRoleArn
    AWS_DEPLOY_ROLE_ARN = $oidc.DeployRoleArn
    ECR_AI_REPOSITORY = $foundation.AiRepositoryName
    ECR_BACKEND_REPOSITORY = $foundation.BackendRepositoryName
    ECR_FRONTEND_REPOSITORY = $foundation.FrontendRepositoryName
    ECS_CLUSTER = $foundation.EcsClusterName
    ECS_AI_SERVICE = $application.AiServiceName
    ECS_BACKEND_SERVICE = $application.BackendServiceName
    ECS_FRONTEND_SERVICE = $application.FrontendServiceName
    ECS_AI_TASK_FAMILY = $application.AiTaskFamily
    ECS_BACKEND_TASK_FAMILY = $application.BackendTaskFamily
    ECS_FRONTEND_TASK_FAMILY = $application.FrontendTaskFamily
    ECS_AI_CONTAINER_NAME = $application.AiContainerName
    ECS_BACKEND_CONTAINER_NAME = $application.BackendContainerName
    ECS_FRONTEND_CONTAINER_NAME = $application.FrontendContainerName
    FRONTEND_URL = $baseUrl
    FRONTEND_HEALTH_URL = "$baseUrl/_stcore/health"
    BACKEND_HEALTH_URL = "$baseUrl/health"
    COACH_SMOKE_URL = "$baseUrl/api/coach"
}

foreach ($item in $variables.GetEnumerator()) {
    Invoke-Gh variable set $item.Key --repo $Repository --body $item.Value
}

$secretJson = Invoke-Aws secretsmanager get-secret-value `
    --secret-id $foundation.BackendApiKeySecretArn `
    --region $Region `
    --query SecretString `
    --output text
$backendApiKey = ($secretJson | ConvertFrom-Json).value
$backendApiKey | & $Gh secret set SMOKE_BACKEND_API_KEY --repo $Repository --env demo
if ($LASTEXITCODE -ne 0) {
    throw "Could not set the protected demo smoke-test secret."
}

Invoke-Gh repo edit $Repository `
    --enable-issues=false `
    --enable-wiki=false `
    --enable-projects=false `
    --enable-secret-scanning `
    --enable-secret-scanning-push-protection

Write-Host "Configured GitHub Actions variables, the demo environment, OIDC defaults, and the smoke-test secret."
