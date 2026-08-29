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
$educationKnowledgeBaseId = $application.EducationKnowledgeBaseId
if (-not $educationKnowledgeBaseId) {
    $educationKnowledgeBaseId = Invoke-Aws cloudformation describe-stacks `
        --stack-name $ApplicationStack `
        --region $Region `
        --query "Stacks[0].Parameters[?ParameterKey=='EducationKnowledgeBaseId'].ParameterValue | [0]" `
        --output text
}
$educationDataSourceId = Invoke-Aws bedrock-agent list-data-sources `
    --knowledge-base-id $educationKnowledgeBaseId `
    --region $Region `
    --query "dataSourceSummaries[?status=='AVAILABLE'].dataSourceId | [0]" `
    --output text
if (-not $educationDataSourceId -or $educationDataSourceId -eq "None") {
    throw "An available Education Knowledge Base data source is required."
}
$educationDataSource = Invoke-Aws bedrock-agent get-data-source `
    --knowledge-base-id $educationKnowledgeBaseId `
    --data-source-id $educationDataSourceId `
    --region $Region `
    --query "dataSource.dataSourceConfiguration.s3Configuration" `
    --output json | ConvertFrom-Json
$educationSourceBucket = $educationDataSource.bucketArn.Replace("arn:aws:s3:::", "")
$educationSourcePrefix = [string]$educationDataSource.inclusionPrefixes[0]
if (-not $educationSourceBucket -or -not $educationSourcePrefix) {
    throw "Education data source must expose a governed S3 bucket and prefix."
}
$policyKnowledgeBaseId = $application.PolicyKnowledgeBaseId
if (-not $policyKnowledgeBaseId) {
    $policyKnowledgeBaseId = Invoke-Aws cloudformation describe-stacks `
        --stack-name $ApplicationStack `
        --region $Region `
        --query "Stacks[0].Parameters[?ParameterKey=='PolicyKnowledgeBaseId'].ParameterValue | [0]" `
        --output text
}
$policyDataSourceId = Invoke-Aws bedrock-agent list-data-sources `
    --knowledge-base-id $policyKnowledgeBaseId `
    --region $Region `
    --query "dataSourceSummaries[?status=='AVAILABLE'].dataSourceId | [0]" `
    --output text
if (-not $policyDataSourceId -or $policyDataSourceId -eq "None") {
    throw "An available Policy Knowledge Base data source is required."
}
$policyDataSource = Invoke-Aws bedrock-agent get-data-source `
    --knowledge-base-id $policyKnowledgeBaseId `
    --data-source-id $policyDataSourceId `
    --region $Region `
    --query "dataSource.dataSourceConfiguration.s3Configuration" `
    --output json | ConvertFrom-Json
$policySourceBucket = $policyDataSource.bucketArn.Replace("arn:aws:s3:::", "")
$policySourcePrefix = [string]$policyDataSource.inclusionPrefixes[0]
if (-not $policySourceBucket -or -not $policySourcePrefix) {
    throw "Policy data source must expose a governed S3 bucket and prefix."
}
$baseUrl = "http://$($foundation.LoadBalancerDnsName)"

$oidcBody = @{ use_default = $true } | ConvertTo-Json -Compress
$oidcBody | & $Gh api --method PUT "repos/$Repository/actions/oidc/customization/sub" --input -
if ($LASTEXITCODE -ne 0) {
    throw "Could not enforce the default GitHub OIDC subject format."
}

$environmentBody = @{
    wait_timer = 0
    prevent_self_review = $false
    reviewers = @()
    deployment_branch_policy = @{
        protected_branches = $false
        custom_branch_policies = $true
    }
} | ConvertTo-Json -Depth 5
$existingEnvironment = & $Gh api "repos/$Repository/environments/demo" 2>$null
$environmentExists = $LASTEXITCODE -eq 0
$environmentOutput = $environmentBody | & $Gh api --method PUT `
    "repos/$Repository/environments/demo" --input - 2>&1
if ($LASTEXITCODE -ne 0) {
    if (-not $environmentExists) {
        throw "Could not create the GitHub demo environment: $environmentOutput"
    }
    Write-Warning "The existing demo environment could not be updated because its protection settings are unavailable on the current repository plan. Existing settings are preserved."
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
    BEDROCK_MODEL_ID = $application.BedrockModelId
    EDUCATION_KNOWLEDGE_BASE_ID = $educationKnowledgeBaseId
    EDUCATION_CORPUS_VERSION = $application.EducationCorpusVersion
    EDUCATION_DATA_SOURCE_ID = $educationDataSourceId
    EDUCATION_SOURCE_BUCKET = $educationSourceBucket
    EDUCATION_SOURCE_PREFIX = $educationSourcePrefix
    POLICY_KNOWLEDGE_BASE_ID = $policyKnowledgeBaseId
    POLICY_CORPUS_VERSION = $application.PolicyCorpusVersion
    POLICY_DATA_SOURCE_ID = $policyDataSourceId
    POLICY_SOURCE_BUCKET = $policySourceBucket
    POLICY_SOURCE_PREFIX = $policySourcePrefix
    OPERATIONAL_DASHBOARD_NAME = $application.OperationalDashboardName
    OPERATIONAL_ALARM_PREFIX = $application.OperationalAlarmPrefix
    LIVE_EVAL_MAX_P95_MS = "10000"
    LIVE_EVAL_MAX_COST_USD = "0.05"
    LOAD_MAX_P95_MS = "8000"
    AWS_OPERATIONAL_VALIDATION_ENABLED = "true"
    RAG_SOURCE_GOVERNANCE_ENABLED = "true"
    POLICY_RAG_SOURCE_GOVERNANCE_ENABLED = "true"
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
    throw "Could not set the demo smoke-test secret."
}

Invoke-Gh repo edit $Repository `
    --enable-issues=false `
    --enable-wiki=false `
    --enable-projects=false

$securityOutput = & $Gh repo edit $Repository `
    --enable-secret-scanning `
    --enable-secret-scanning-push-protection 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Secret scanning or push protection is unavailable for this repository plan: $securityOutput"
}

Write-Host "Configured GitHub Actions variables, the main-only demo environment, OIDC defaults, and the smoke-test secret."
Write-Host "release.yml automatically deploys the current main SHA after successful push CI."
