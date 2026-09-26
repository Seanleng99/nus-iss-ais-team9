param(
    [string]$AccountId = "862124275471",
    [string]$Region = "ap-southeast-1",
    [string]$Repository = "Seanleng99/nus-iss-ais-team9",
    [string]$FoundationStack = "ai-financial-wellness-coach-foundation",
    [string]$ApplicationStack = "ai-financial-wellness-coach-application",
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$ExpectedReleaseSha,
    [string]$ExpectedFrontendReleaseSha = "",
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

function Get-ServiceTaskDefinition {
    param([string]$ClusterName, [string]$ServiceName)
    $taskDefinition = Invoke-Aws ecs describe-services `
        --cluster $ClusterName `
        --services $ServiceName `
        --region $Region `
        --query "services[0].taskDefinition" `
        --output text
    if (-not $taskDefinition -or $taskDefinition -eq "None") {
        throw "Could not resolve the task definition attached to stable service $ServiceName."
    }
    return $taskDefinition
}

function Get-ContainerImage {
    param([string]$TaskDefinition, [string]$ContainerName)
    $image = Invoke-Aws ecs describe-task-definition `
        --task-definition $TaskDefinition `
        --region $Region `
        --query "taskDefinition.containerDefinitions[?name=='$ContainerName'].image | [0]" `
        --output text
    if (-not $image -or $image -eq "None") {
        throw "Could not resolve container $ContainerName in task definition $TaskDefinition."
    }
    return $image
}

function Get-RunnableTaskDefinition {
    param([string]$TaskDefinition)
    $definition = Invoke-Aws ecs describe-task-definition `
        --task-definition $TaskDefinition `
        --region $Region `
        --query "taskDefinition" `
        --output json | ConvertFrom-Json
    if ($definition.status -eq "ACTIVE") {
        return $TaskDefinition
    }
    if ($definition.status -ne "INACTIVE") {
        throw "Task definition $TaskDefinition has unexpected status $($definition.status)."
    }

    Write-Host "Cloning inactive deployed task definition $TaskDefinition for the ownership migration..."
    $registration = [ordered]@{
        family = $definition.family
        taskRoleArn = $definition.taskRoleArn
        executionRoleArn = $definition.executionRoleArn
        networkMode = $definition.networkMode
        containerDefinitions = $definition.containerDefinitions
        volumes = $definition.volumes
        placementConstraints = $definition.placementConstraints
        requiresCompatibilities = $definition.requiresCompatibilities
        cpu = $definition.cpu
        memory = $definition.memory
        proxyConfiguration = $definition.proxyConfiguration
        ipcMode = $definition.ipcMode
        pidMode = $definition.pidMode
        inferenceAccelerators = $definition.inferenceAccelerators
        ephemeralStorage = $definition.ephemeralStorage
        runtimePlatform = $definition.runtimePlatform
    }
    foreach ($key in @($registration.Keys)) {
        $value = $registration[$key]
        if (
            $null -eq $value -or
            ($value -is [string] -and -not $value) -or
            ($value -is [array] -and $value.Count -eq 0)
        ) {
            $registration.Remove($key)
        }
    }
    $registrationJson = $registration | ConvertTo-Json -Depth 100 -Compress
    $registeredTaskDefinition = Invoke-Aws ecs register-task-definition `
        --cli-input-json $registrationJson `
        --region $Region `
        --query "taskDefinition.taskDefinitionArn" `
        --output text
    if (-not $registeredTaskDefinition -or $registeredTaskDefinition -eq "None") {
        throw "ECS did not register a runnable copy of $TaskDefinition."
    }
    return $registeredTaskDefinition
}

if ($Confirmation -cne "ACTIVATE-OIDC") {
    throw "Pass -Confirmation ACTIVATE-OIDC to provision Cognito/CloudFront and enforce user authentication."
}
if (-not $ExpectedFrontendReleaseSha) {
    $ExpectedFrontendReleaseSha = $ExpectedReleaseSha
}
if ($ExpectedFrontendReleaseSha -notmatch "^[0-9a-f]{40}$") {
    throw "ExpectedFrontendReleaseSha must be a lowercase 40-character Git SHA."
}

$identity = Invoke-Aws sts get-caller-identity --output json | ConvertFrom-Json
if ($identity.Account -ne $AccountId) {
    throw "Authenticated AWS account $($identity.Account) does not match expected account $AccountId"
}

$cloudFrontOriginPrefixListId = Invoke-Aws ec2 describe-managed-prefix-lists `
    --filters "Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing" `
    --region $Region `
    --query "PrefixLists[0].PrefixListId" `
    --output text
if (-not $cloudFrontOriginPrefixListId -or $cloudFrontOriginPrefixListId -eq "None") {
    throw "The regional CloudFront origin-facing managed prefix list was not found."
}

$foundationBefore = Get-StackOutputs $FoundationStack
$applicationBefore = Get-StackOutputs $ApplicationStack
if (-not $applicationBefore.EducationKnowledgeBaseId -or -not $applicationBefore.PolicyKnowledgeBaseId) {
    throw "The application stack must expose both governed Knowledge Base IDs."
}

Invoke-Aws ecs wait services-stable `
    --cluster $foundationBefore.EcsClusterName `
    --services `
        $applicationBefore.BackendServiceName `
        $applicationBefore.FrontendServiceName `
        $applicationBefore.AiServiceName `
    --region $Region
$deployedBackendTaskDefinition = Get-ServiceTaskDefinition `
    $foundationBefore.EcsClusterName $applicationBefore.BackendServiceName
$deployedFrontendTaskDefinition = Get-ServiceTaskDefinition `
    $foundationBefore.EcsClusterName $applicationBefore.FrontendServiceName
$deployedAiTaskDefinition = Get-ServiceTaskDefinition `
    $foundationBefore.EcsClusterName $applicationBefore.AiServiceName
$backendImage = Get-ContainerImage `
    $deployedBackendTaskDefinition $applicationBefore.BackendContainerName
$frontendImage = Get-ContainerImage `
    $deployedFrontendTaskDefinition $applicationBefore.FrontendContainerName
$aiImage = Get-ContainerImage `
    $deployedAiTaskDefinition $applicationBefore.AiContainerName
if (-not $backendImage -or -not $backendImage.EndsWith(":$ExpectedReleaseSha")) {
    throw "The deployed backend image '$backendImage' does not match release $ExpectedReleaseSha. Release the authentication code before activating OIDC."
}
if (-not $frontendImage.EndsWith(":$ExpectedFrontendReleaseSha")) {
    throw "The deployed frontend image '$frontendImage' does not match release $ExpectedFrontendReleaseSha. Release the authentication code before activating OIDC."
}
$migrationBackendTaskDefinition = Get-RunnableTaskDefinition `
    $deployedBackendTaskDefinition

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
    --task-definition $migrationBackendTaskDefinition `
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
        "CloudFrontOriginPrefixListId=$cloudFrontOriginPrefixListId" `
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
    "FrontendOidcCookieSecretArn",
    "CloudFrontOriginSecretArn"
)
foreach ($name in $requiredOutputs) {
    if (-not $foundation[$name]) {
        throw "Foundation stack did not expose required authentication output $name."
    }
}

Write-Host "Enforcing OIDC and removing the frontend automation credential..."
$applicationParameters = @(
    "AiServiceImageUri=$aiImage",
    "BackendImageUri=$backendImage",
    "FrontendImageUri=$frontendImage",
    "CloudFrontOriginSecretArn=$($foundation.CloudFrontOriginSecretArn)",
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

[ordered]@{
    FrontendUrl = $foundation.FrontendUrl
    UserPoolId = $foundation.OidcUserPoolId
    ClientId = $foundation.OidcClientId
    RedirectUri = $foundation.OidcRedirectUri
    DemoUserInvited = [bool]$DemoUserEmail
} | ConvertTo-Json
