param(
    [string]$AccountId = "902552928492",
    [string]$Region = "ap-southeast-1",
    [string]$Repository = "Seanleng99/nus-iss-ais-team9",
    [string]$FoundationStack = "ai-financial-wellness-coach-foundation",
    [string]$ApplicationStack = "ai-financial-wellness-coach-application",
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$ExpectedReleaseSha,
    [string]$DemoUserEmail = "",
    [string]$Confirmation = ""
)

$ErrorActionPreference = "Stop"
$Aws = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Invoke-Aws {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $Aws @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "AWS CLI command failed: aws $($Arguments -join ' ')"
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

if ($Confirmation -cne "ACTIVATE-OIDC") {
    throw "Pass -Confirmation ACTIVATE-OIDC to provision Cognito/CloudFront and enforce user authentication."
}

$identity = Invoke-Aws sts get-caller-identity --output json | ConvertFrom-Json
if ($identity.Account -ne $AccountId) {
    throw "Authenticated AWS account $($identity.Account) does not match expected account $AccountId"
}

$foundationBefore = Get-StackOutputs $FoundationStack
$applicationBefore = Get-StackOutputs $ApplicationStack
if (-not $applicationBefore.EducationKnowledgeBaseId -or -not $applicationBefore.PolicyKnowledgeBaseId) {
    throw "The application stack must expose both governed Knowledge Base IDs."
}

Invoke-Aws ecs wait services-stable `
    --cluster $foundationBefore.EcsClusterName `
    --services $applicationBefore.BackendServiceName `
    --region $Region
$deployedBackendTaskDefinition = Invoke-Aws ecs describe-services `
    --cluster $foundationBefore.EcsClusterName `
    --services $applicationBefore.BackendServiceName `
    --region $Region `
    --query "services[0].taskDefinition" `
    --output text
if (-not $deployedBackendTaskDefinition -or $deployedBackendTaskDefinition -eq "None") {
    throw "Could not resolve the task definition attached to the stable backend service."
}
$backendImage = Invoke-Aws ecs describe-task-definition `
    --task-definition $deployedBackendTaskDefinition `
    --region $Region `
    --query "taskDefinition.containerDefinitions[?name=='$($applicationBefore.BackendContainerName)'].image | [0]" `
    --output text
if (-not $backendImage -or -not $backendImage.EndsWith(":$ExpectedReleaseSha")) {
    throw "The deployed backend image '$backendImage' does not match release $ExpectedReleaseSha. Release the authentication code before activating OIDC."
}

Write-Host "Applying the ownership migration before authentication is enforced..."
$network = "awsvpcConfiguration={subnets=[$($foundationBefore.PublicSubnetAId),$($foundationBefore.PublicSubnetBId)],securityGroups=[$($foundationBefore.BackendSecurityGroupId)],assignPublicIp=ENABLED}"
$overrides = @{
    containerOverrides = @(
        @{
            name = $applicationBefore.BackendContainerName
            command = @("alembic", "upgrade", "head")
        }
    )
} | ConvertTo-Json -Depth 5 -Compress
$taskArn = Invoke-Aws ecs run-task `
    --cluster $foundationBefore.EcsClusterName `
    --task-definition $deployedBackendTaskDefinition `
    --launch-type FARGATE `
    --network-configuration $network `
    --overrides $overrides `
    --region $Region `
    --query "tasks[0].taskArn" `
    --output text
if (-not $taskArn -or $taskArn -eq "None") {
    throw "ECS did not start the ownership migration task."
}
Invoke-Aws ecs wait tasks-stopped `
    --cluster $foundationBefore.EcsClusterName `
    --tasks $taskArn `
    --region $Region
$exitCode = Invoke-Aws ecs describe-tasks `
    --cluster $foundationBefore.EcsClusterName `
    --tasks $taskArn `
    --region $Region `
    --query "tasks[0].containers[?name=='$($applicationBefore.BackendContainerName)'].exitCode | [0]" `
    --output text
if ($exitCode -ne "0") {
    throw "Ownership migration failed with exit code $exitCode. Authentication was not activated."
}

Write-Host "Provisioning the HTTPS and Cognito identity boundary..."
Invoke-Aws cloudformation deploy `
    --template-file (Join-Path $ProjectRoot "infra\aws\demo-foundation.yaml") `
    --stack-name $FoundationStack `
    --region $Region `
    --capabilities CAPABILITY_NAMED_IAM `
    --parameter-overrides `
        "EducationKnowledgeBaseId=$($applicationBefore.EducationKnowledgeBaseId)" `
        "PolicyKnowledgeBaseId=$($applicationBefore.PolicyKnowledgeBaseId)" `
    --no-fail-on-empty-changeset `
    --tags Project=ai-financial-wellness-coach Environment=demo

$foundation = Get-StackOutputs $FoundationStack
$requiredOutputs = @(
    "FrontendUrl",
    "OidcIssuerUrl",
    "OidcJwksUrl",
    "OidcClientId",
    "OidcServerMetadataUrl",
    "OidcRedirectUri",
    "FrontendOidcCookieSecretArn"
)
foreach ($name in $requiredOutputs) {
    if (-not $foundation[$name]) {
        throw "Foundation stack did not expose required authentication output $name."
    }
}

Write-Host "Enforcing OIDC and removing the frontend automation credential..."
$applicationParameters = @(
    "FrontendUrl=$($foundation.FrontendUrl)",
    "OidcIssuerUrl=$($foundation.OidcIssuerUrl)",
    "OidcJwksUrl=$($foundation.OidcJwksUrl)",
    "OidcClientId=$($foundation.OidcClientId)",
    "OidcServerMetadataUrl=$($foundation.OidcServerMetadataUrl)",
    "OidcRedirectUri=$($foundation.OidcRedirectUri)",
    "FrontendOidcCookieSecretArn=$($foundation.FrontendOidcCookieSecretArn)"
)
Invoke-Aws cloudformation deploy `
    --template-file (Join-Path $ProjectRoot "infra\aws\demo-application.yaml") `
    --stack-name $ApplicationStack `
    --region $Region `
    --parameter-overrides @applicationParameters `
    --no-fail-on-empty-changeset `
    --tags Project=ai-financial-wellness-coach Environment=demo

if ($DemoUserEmail) {
    $existingUser = & $Aws cognito-idp admin-get-user `
        --user-pool-id $foundation.OidcUserPoolId `
        --username $DemoUserEmail `
        --region $Region `
        --output json 2>$null
    if ($LASTEXITCODE -ne 0) {
        Invoke-Aws cognito-idp admin-create-user `
            --user-pool-id $foundation.OidcUserPoolId `
            --username $DemoUserEmail `
            --user-attributes "Name=email,Value=$DemoUserEmail" `
            --desired-delivery-mediums EMAIL `
            --region $Region | Out-Null
        Write-Host "Created the invited synthetic-demo user."
    } else {
        $null = $existingUser
        Write-Host "The requested synthetic-demo user already exists."
    }
}

& (Join-Path $PSScriptRoot "configure_github.ps1") `
    -Repository $Repository `
    -Region $Region `
    -FoundationStack $FoundationStack `
    -ApplicationStack $ApplicationStack
if ($LASTEXITCODE -ne 0) {
    throw "GitHub configuration refresh failed after authentication activation."
}

[ordered]@{
    FrontendUrl = $foundation.FrontendUrl
    UserPoolId = $foundation.OidcUserPoolId
    ClientId = $foundation.OidcClientId
    RedirectUri = $foundation.OidcRedirectUri
    DemoUserInvited = [bool]$DemoUserEmail
} | ConvertTo-Json
