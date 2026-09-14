param(
    [string]$AccountId = "902552928492",
    [string]$Region = "ap-southeast-1",
    [string]$Repository = "Seanleng99/nus-iss-ais-team9",
    [string]$FoundationStack = "ai-financial-wellness-coach-foundation",
    [string]$ApplicationStack = "ai-financial-wellness-coach-application",
    [string]$OidcStack = "ai-financial-wellness-coach-github-oidc",
    [string]$BedrockInferenceProfileId = "apac.amazon.nova-lite-v1:0",
    [string]$BedrockFoundationModelId = "amazon.nova-lite-v1:0",
    [string]$BedrockComparisonInferenceProfileId = "apac.amazon.nova-micro-v1:0",
    [string]$BedrockComparisonFoundationModelId = "amazon.nova-micro-v1:0",
    [string]$EducationKnowledgeBaseId = "",
    [string]$EducationDataSourceId = "",
    [string]$EducationSourceBucketName = "",
    [string]$EducationSourcePrefix = "investment-education/documents/",
    [string]$PolicyKnowledgeBaseId = "",
    [string]$PolicyDataSourceId = "",
    [string]$PolicySourceBucketName = "",
    [string]$PolicySourcePrefix = "policy-controls/documents/"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Aws = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
$Gh = "C:\Program Files\GitHub CLI\gh.exe"

foreach ($path in @($Aws, $Gh)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required CLI was not found at $path"
    }
}

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

$identity = Invoke-Aws sts get-caller-identity --output json | ConvertFrom-Json
if ($identity.Account -ne $AccountId) {
    throw "Authenticated AWS account $($identity.Account) does not match $AccountId"
}

Invoke-Gh auth status
$viewer = (Invoke-Gh api user | ConvertFrom-Json).login
if ($viewer -ne $Repository.Split("/")[0]) {
    throw "GitHub CLI is authenticated as $viewer, not $($Repository.Split('/')[0])."
}

$oidcBody = @{ use_default = $true } | ConvertTo-Json -Compress
$oidcBody | & $Gh api --method PUT "repos/$Repository/actions/oidc/customization/sub" --input -
if ($LASTEXITCODE -ne 0) {
    throw "Could not enforce the default GitHub OIDC subject format."
}
$oidcConfig = Invoke-Gh api "repos/$Repository/actions/oidc/customization/sub" |
    ConvertFrom-Json
$subjectPrefix = $oidcConfig.sub_claim_prefix
if (-not $oidcConfig.use_default -or -not $subjectPrefix.StartsWith("repo:")) {
    throw "GitHub did not return a usable default OIDC subject prefix."
}

$foundation = Get-StackOutputs $FoundationStack
$application = Get-StackOutputs $ApplicationStack
if (-not $EducationKnowledgeBaseId) {
    $EducationKnowledgeBaseId = Invoke-Aws cloudformation describe-stacks `
        --stack-name $ApplicationStack `
        --region $Region `
        --query "Stacks[0].Parameters[?ParameterKey=='EducationKnowledgeBaseId'].ParameterValue | [0]" `
        --output text
}
if (-not $EducationDataSourceId) {
    $EducationDataSourceId = Invoke-Aws bedrock-agent list-data-sources `
        --knowledge-base-id $EducationKnowledgeBaseId `
        --region $Region `
        --query "dataSourceSummaries[?status=='AVAILABLE'].dataSourceId | [0]" `
        --output text
}
if (-not $EducationKnowledgeBaseId -or $EducationKnowledgeBaseId -eq "None" -or
    -not $EducationDataSourceId -or $EducationDataSourceId -eq "None") {
    throw "The Education Knowledge Base and an available data source are required."
}
$educationDataSource = Invoke-Aws bedrock-agent get-data-source `
    --knowledge-base-id $EducationKnowledgeBaseId `
    --data-source-id $EducationDataSourceId `
    --region $Region `
    --query "dataSource.dataSourceConfiguration.s3Configuration" `
    --output json | ConvertFrom-Json
if (-not $EducationSourceBucketName) {
    $EducationSourceBucketName = $educationDataSource.bucketArn.Replace("arn:aws:s3:::", "")
}
if ($educationDataSource.inclusionPrefixes -notcontains $EducationSourcePrefix) {
    throw "Education source prefix does not match the Bedrock data source."
}
if (-not $PolicyKnowledgeBaseId) {
    $PolicyKnowledgeBaseId = Invoke-Aws cloudformation describe-stacks `
        --stack-name $ApplicationStack `
        --region $Region `
        --query "Stacks[0].Parameters[?ParameterKey=='PolicyKnowledgeBaseId'].ParameterValue | [0]" `
        --output text
}
if (-not $PolicyDataSourceId) {
    $PolicyDataSourceId = Invoke-Aws bedrock-agent list-data-sources `
        --knowledge-base-id $PolicyKnowledgeBaseId `
        --region $Region `
        --query "dataSourceSummaries[?status=='AVAILABLE'].dataSourceId | [0]" `
        --output text
}
if (-not $PolicyKnowledgeBaseId -or $PolicyKnowledgeBaseId -eq "None" -or
    -not $PolicyDataSourceId -or $PolicyDataSourceId -eq "None") {
    throw "The Policy Knowledge Base and an available data source are required."
}
$policyDataSource = Invoke-Aws bedrock-agent get-data-source `
    --knowledge-base-id $PolicyKnowledgeBaseId `
    --data-source-id $PolicyDataSourceId `
    --region $Region `
    --query "dataSource.dataSourceConfiguration.s3Configuration" `
    --output json | ConvertFrom-Json
if (-not $PolicySourceBucketName) {
    $PolicySourceBucketName = $policyDataSource.bucketArn.Replace("arn:aws:s3:::", "")
}
if ($policyDataSource.inclusionPrefixes -notcontains $PolicySourcePrefix) {
    throw "Policy source prefix does not match the Bedrock data source."
}
$ownedProviderArn = & $Aws cloudformation describe-stack-resource `
    --stack-name $OidcStack `
    --logical-resource-id GitHubOidcProvider `
    --region $Region `
    --query "StackResourceDetail.PhysicalResourceId" `
    --output text 2>$null
if ($LASTEXITCODE -eq 0 -and $ownedProviderArn -and $ownedProviderArn -ne "None") {
    $providerArn = ""
} else {
    $providerArn = Invoke-Aws iam list-open-id-connect-providers `
        --query "OpenIDConnectProviderList[?contains(Arn, 'token.actions.githubusercontent.com')].Arn | [0]" `
        --output text
    if ($providerArn -eq "None") { $providerArn = "" }
}

$parameters = @(
    "ExistingGitHubOidcProviderArn=$providerArn",
    "PublishSubjectClaim=$subjectPrefix`:ref:refs/heads/main",
    "DeploySubjectClaim=$subjectPrefix`:environment:demo",
    "EcrAiRepository=$($foundation.AiRepositoryName)",
    "EcrBackendRepository=$($foundation.BackendRepositoryName)",
    "EcrFrontendRepository=$($foundation.FrontendRepositoryName)",
    "EcsClusterName=$($foundation.EcsClusterName)",
    "EcsAiServiceName=$($application.AiServiceName)",
    "EcsBackendServiceName=$($application.BackendServiceName)",
    "EcsFrontendServiceName=$($application.FrontendServiceName)",
    "EcsBackendTaskFamily=$($application.BackendTaskFamily)",
    "EcsTaskExecutionRoleArn=$($foundation.TaskExecutionRoleArn)",
    "EcsAppTaskRoleArn=$($foundation.AppTaskRoleArn)",
    "EcsAiTaskRoleArn=$($foundation.AiTaskRoleArn)",
    "BedrockBaselineInferenceProfileId=$BedrockInferenceProfileId",
    "BedrockBaselineFoundationModelId=$BedrockFoundationModelId",
    "BedrockCandidateInferenceProfileId=$BedrockComparisonInferenceProfileId",
    "BedrockCandidateFoundationModelId=$BedrockComparisonFoundationModelId",
    "EducationKnowledgeBaseId=$EducationKnowledgeBaseId",
    "EducationSourceBucketName=$EducationSourceBucketName",
    "EducationSourcePrefix=$EducationSourcePrefix",
    "PolicyKnowledgeBaseId=$PolicyKnowledgeBaseId",
    "PolicySourceBucketName=$PolicySourceBucketName",
    "PolicySourcePrefix=$PolicySourcePrefix",
    "OperationalAlertsTopicArn=$($application.OperationalAlertsTopicArn)"
)

if ($foundation.BackendTaskRoleArn) {
    $parameters += "EcsBackendTaskRoleArn=$($foundation.BackendTaskRoleArn)"
}
Invoke-Aws cloudformation deploy `
    --template-file (Join-Path $ProjectRoot "infra\aws\github-actions-oidc.yaml") `
    --stack-name $OidcStack `
    --region $Region `
    --parameter-overrides @parameters `
    --capabilities CAPABILITY_NAMED_IAM `
    --no-fail-on-empty-changeset `
    --tags Project=ai-financial-wellness-coach Environment=demo

Write-Host "Updated GitHub OIDC roles with approved model, RAG audit, and operational-alert inspection scopes."
