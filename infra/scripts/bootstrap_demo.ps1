param(
    [string]$AccountId = "902552928492",
    [string]$Region = "ap-southeast-1",
    [string]$Repository = "Seanleng99/nus-iss-ais-team9",
    [string]$FoundationStack = "ai-financial-wellness-coach-foundation",
    [string]$ApplicationStack = "ai-financial-wellness-coach-application",
    [string]$OidcStack = "ai-financial-wellness-coach-github-oidc"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Aws = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
$Gh = "C:\Program Files\GitHub CLI\gh.exe"

if (-not (Test-Path -LiteralPath $Aws)) {
    throw "AWS CLI was not found at $Aws"
}
if (-not (Test-Path -LiteralPath $Gh)) {
    throw "GitHub CLI was not found at $Gh"
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

$identity = (Invoke-Aws sts get-caller-identity --output json | ConvertFrom-Json)
if ($identity.Account -ne $AccountId) {
    throw "Authenticated AWS account $($identity.Account) does not match expected account $AccountId"
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
$oidcConfig = Invoke-Gh api "repos/$Repository/actions/oidc/customization/sub" | ConvertFrom-Json
$subjectPrefix = $oidcConfig.sub_claim_prefix
if (-not $subjectPrefix -or -not $subjectPrefix.StartsWith("repo:")) {
    throw "GitHub did not return a usable OIDC subject prefix."
}

& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop must be running before bootstrapping the demo."
}

Write-Host "Deploying shared foundation stack..."
Invoke-Aws cloudformation deploy `
    --template-file (Join-Path $ProjectRoot "infra\aws\demo-foundation.yaml") `
    --stack-name $FoundationStack `
    --region $Region `
    --capabilities CAPABILITY_NAMED_IAM `
    --no-fail-on-empty-changeset `
    --tags Project=ai-financial-wellness-coach Environment=demo

$foundation = Get-StackOutputs $FoundationStack
$registry = $foundation.AiRepositoryUri.Split("/")[0]
$bootstrapTag = "bootstrap-$(Get-Date -Format 'yyyyMMddHHmmss')"

Write-Host "Authenticating Docker to ECR..."
$password = Invoke-Aws ecr get-login-password --region $Region
$password | & docker login --username AWS --password-stdin $registry
if ($LASTEXITCODE -ne 0) {
    throw "Docker could not authenticate to ECR."
}

$images = @{
    Ai = "$($foundation.AiRepositoryUri):$bootstrapTag"
    Backend = "$($foundation.BackendRepositoryUri):$bootstrapTag"
    Frontend = "$($foundation.FrontendRepositoryUri):$bootstrapTag"
}

Write-Host "Building and publishing initial immutable images..."
& docker build -f (Join-Path $ProjectRoot "infra\docker\Dockerfile.ai-service") -t $images.Ai $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw "AI image build failed." }
& docker build -f (Join-Path $ProjectRoot "infra\docker\Dockerfile.backend") -t $images.Backend $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw "Backend image build failed." }
& docker build -f (Join-Path $ProjectRoot "infra\docker\Dockerfile.frontend") -t $images.Frontend $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw "Frontend image build failed." }

foreach ($image in $images.Values) {
    & docker push $image
    if ($LASTEXITCODE -ne 0) { throw "Image push failed: $image" }
}

Write-Host "Deploying ECS application stack..."
$applicationParameters = @(
    "VpcId=$($foundation.VpcId)",
    "PublicSubnetAId=$($foundation.PublicSubnetAId)",
    "PublicSubnetBId=$($foundation.PublicSubnetBId)",
    "FrontendSecurityGroupId=$($foundation.FrontendSecurityGroupId)",
    "BackendSecurityGroupId=$($foundation.BackendSecurityGroupId)",
    "AiSecurityGroupId=$($foundation.AiSecurityGroupId)",
    "LoadBalancerArn=$($foundation.LoadBalancerArn)",
    "EcsClusterName=$($foundation.EcsClusterName)",
    "ServiceDiscoveryNamespaceId=$($foundation.ServiceDiscoveryNamespaceId)",
    "TaskExecutionRoleArn=$($foundation.TaskExecutionRoleArn)",
    "AppTaskRoleArn=$($foundation.AppTaskRoleArn)",
    "AiTaskRoleArn=$($foundation.AiTaskRoleArn)",
    "BackendApiKeySecretArn=$($foundation.BackendApiKeySecretArn)",
    "AiServiceApiKeySecretArn=$($foundation.AiServiceApiKeySecretArn)",
    "AiLogGroupName=$($foundation.AiLogGroupName)",
    "BackendLogGroupName=$($foundation.BackendLogGroupName)",
    "FrontendLogGroupName=$($foundation.FrontendLogGroupName)",
    "AiImageUri=$($images.Ai)",
    "BackendImageUri=$($images.Backend)",
    "FrontendImageUri=$($images.Frontend)"
)
Invoke-Aws cloudformation deploy `
    --template-file (Join-Path $ProjectRoot "infra\aws\demo-application.yaml") `
    --stack-name $ApplicationStack `
    --region $Region `
    --parameter-overrides @applicationParameters `
    --no-fail-on-empty-changeset `
    --tags Project=ai-financial-wellness-coach Environment=demo

$application = Get-StackOutputs $ApplicationStack
$providerArn = Invoke-Aws iam list-open-id-connect-providers `
    --query "OpenIDConnectProviderList[?contains(Arn, 'token.actions.githubusercontent.com')].Arn | [0]" `
    --output text
if ($providerArn -eq "None") { $providerArn = "" }

Write-Host "Deploying GitHub OIDC roles..."
$oidcParameters = @(
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
    "EcsTaskExecutionRoleArn=$($foundation.TaskExecutionRoleArn)",
    "EcsAppTaskRoleArn=$($foundation.AppTaskRoleArn)",
    "EcsAiTaskRoleArn=$($foundation.AiTaskRoleArn)"
)
Invoke-Aws cloudformation deploy `
    --template-file (Join-Path $ProjectRoot "infra\aws\github-actions-oidc.yaml") `
    --stack-name $OidcStack `
    --region $Region `
    --parameter-overrides @oidcParameters `
    --capabilities CAPABILITY_NAMED_IAM `
    --no-fail-on-empty-changeset `
    --tags Project=ai-financial-wellness-coach Environment=demo

$oidc = Get-StackOutputs $OidcStack
$summary = [ordered]@{
    AccountId = $AccountId
    Region = $Region
    FoundationStack = $FoundationStack
    ApplicationStack = $ApplicationStack
    OidcStack = $OidcStack
    LoadBalancerDnsName = $foundation.LoadBalancerDnsName
    PublishRoleArn = $oidc.PublishRoleArn
    DeployRoleArn = $oidc.DeployRoleArn
    BootstrapTag = $bootstrapTag
}
$summary | ConvertTo-Json
