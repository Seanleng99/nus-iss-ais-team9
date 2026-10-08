param(
    [string]$AccountId = "862124275471",
    [string]$Region = "ap-southeast-1",
    [string]$Repository = "Seanleng99/nus-iss-ais-team9",
    [string]$FoundationStack = "ai-financial-wellness-coach-foundation",
    [string]$ApplicationStack = "ai-financial-wellness-coach-application",
    [string]$OidcStack = "ai-financial-wellness-coach-github-oidc",
    [string]$AlertEmail = "",
    [switch]$EnableDatabaseCredentialRefresh,
    [string]$LegacyCognitoIssuerUrl = "",
    [string]$ExistingOidcIssuerUrl = "",
    [string]$ExistingOidcClientId = "",
    [string]$ExistingOidcRedirectUri = "",
    [string]$DatabaseInstanceIdentifier = "ai-financial-wellness-coach-demo",
    [string]$DatabaseSnapshotIdentifier = "",
    [string]$EducationCorpusVersion = "investment-education-sg@2026-09-27.2",
    [string]$PolicyCorpusVersion = "financial-coach-policy-sg@2026-10-09.1",
    [string]$OpenAiModelId = "gpt-6-luna"
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
$openAiSecretArn = Invoke-Aws secretsmanager describe-secret `
    --secret-id "ai-financial-wellness-coach/demo/openai-api-key" `
    --region $Region `
    --query ARN `
    --output text
$openAiSecret = Invoke-Aws secretsmanager get-secret-value `
    --secret-id $openAiSecretArn `
    --region $Region `
    --query SecretString `
    --output text | ConvertFrom-Json
if (-not $openAiSecret.'openai-api-key') {
    throw "Populate the existing OpenAI API key secret before deploying the foundation."
}
$openAiSecret = $null
$existingFoundationJson = & $Aws cloudformation describe-stacks `
    --stack-name $FoundationStack `
    --region $Region `
    --query "Stacks[0].Parameters" `
    --output json 2>$null
if ($LASTEXITCODE -eq 0) {
    $existingParameters = @{}
    foreach ($parameter in ($existingFoundationJson | ConvertFrom-Json)) {
        $existingParameters[$parameter.ParameterKey] = $parameter.ParameterValue
    }
    if (-not $PSBoundParameters.ContainsKey("DatabaseSnapshotIdentifier") -and $existingParameters.DatabaseSnapshotIdentifier) {
        $DatabaseSnapshotIdentifier = $existingParameters.DatabaseSnapshotIdentifier
    }
    if (-not $PSBoundParameters.ContainsKey("DatabaseInstanceIdentifier") -and $existingParameters.DatabaseInstanceIdentifier) {
        $DatabaseInstanceIdentifier = $existingParameters.DatabaseInstanceIdentifier
    }
    if ($existingParameters.DatabaseSnapshotIdentifier -and $DatabaseSnapshotIdentifier -ne $existingParameters.DatabaseSnapshotIdentifier -and $DatabaseInstanceIdentifier -eq $existingParameters.DatabaseInstanceIdentifier) {
        throw "Changing a restored database snapshot requires a different DatabaseInstanceIdentifier."
    }
}

$existingAppIssuer = & $Aws cloudformation describe-stacks `
    --stack-name $ApplicationStack `
    --region $Region `
    --query "Stacks[0].Parameters[?ParameterKey=='OidcIssuerUrl'].ParameterValue | [0]" `
    --output text 2>$null
if ($LASTEXITCODE -eq 0 -and $existingAppIssuer -and $existingAppIssuer -ne "None") {
    if (-not $ExistingOidcIssuerUrl) {
        $foundationOidcIssuer = & $Aws cloudformation describe-stacks `
            --stack-name $FoundationStack `
            --region $Region `
            --query "Stacks[0].Outputs[?OutputKey=='OidcIssuerUrl'].OutputValue | [0]" `
            --output text
        if ($existingAppIssuer -ne $foundationOidcIssuer) {
            throw "The existing application uses a different Cognito pool. Pass ExistingOidcIssuerUrl, ExistingOidcClientId, and ExistingOidcRedirectUri to preserve sign-in."
        }
    }
    if ($ExistingOidcIssuerUrl -and $ExistingOidcIssuerUrl.TrimEnd("/") -ne $existingAppIssuer) {
        throw "ExistingOidcIssuerUrl does not match the issuer currently used by the application."
    }
    $existingLegacyIssuer = & $Aws cloudformation describe-stacks `
        --stack-name $ApplicationStack `
        --region $Region `
        --query "Stacks[0].Parameters[?ParameterKey=='OidcLegacyIssuerUrl'].ParameterValue | [0]" `
        --output text
    if (-not $PSBoundParameters.ContainsKey("LegacyCognitoIssuerUrl") -and $existingLegacyIssuer -and $existingLegacyIssuer -ne "None") {
        $LegacyCognitoIssuerUrl = $existingLegacyIssuer
    }
    if ($existingLegacyIssuer -and $existingLegacyIssuer -ne "None" -and $LegacyCognitoIssuerUrl -ne $existingLegacyIssuer) {
        throw "The existing application maps migrated users to a legacy Cognito issuer. Keep LegacyCognitoIssuerUrl unchanged until database ownership is migrated."
    }
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
if (-not $oidcConfig.use_default) {
    throw "GitHub OIDC must use the default subject format for these IAM trust policies."
}
$subjectPrefix = $oidcConfig.sub_claim_prefix
if (-not $subjectPrefix -or -not $subjectPrefix.StartsWith("repo:")) {
    throw "GitHub did not return a usable OIDC subject prefix."
}

$cloudFrontOriginPrefixListId = Invoke-Aws ec2 describe-managed-prefix-lists `
    --filters "Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing" `
    --region $Region `
    --query "PrefixLists[0].PrefixListId" `
    --output text
if (-not $cloudFrontOriginPrefixListId -or $cloudFrontOriginPrefixListId -eq "None") {
    throw "The regional CloudFront origin-facing managed prefix list was not found."
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
    --parameter-overrides `
        "OpenAiApiKeySecretArn=$openAiSecretArn" `
        "DatabaseInstanceIdentifier=$DatabaseInstanceIdentifier" `
        "DatabaseSnapshotIdentifier=$DatabaseSnapshotIdentifier" `
        "CloudFrontOriginPrefixListId=$cloudFrontOriginPrefixListId" `
    --no-fail-on-empty-changeset `
    --tags Project=ai-financial-wellness-coach Environment=demo

$foundation = Get-StackOutputs $FoundationStack
if ($DatabaseSnapshotIdentifier) {
    $databaseSecretArn = Invoke-Aws rds describe-db-instances `
        --db-instance-identifier $foundation.DatabaseInstanceId `
        --region $Region `
        --query "DBInstances[0].MasterUserSecret.SecretArn" `
        --output text
    if (-not $databaseSecretArn -or $databaseSecretArn -eq "None") {
        Write-Host "Enabling a destination-managed master password for the restored database..."
        Invoke-Aws rds modify-db-instance `
            --db-instance-identifier $foundation.DatabaseInstanceId `
            --region $Region `
            --manage-master-user-password `
            --apply-immediately `
            --query "DBInstance.DBInstanceStatus" `
            --output text | Out-Null
        Invoke-Aws rds wait db-instance-available `
            --db-instance-identifier $foundation.DatabaseInstanceId `
            --region $Region
        $databaseSecretArn = Invoke-Aws rds describe-db-instances `
            --db-instance-identifier $foundation.DatabaseInstanceId `
            --region $Region `
            --query "DBInstances[0].MasterUserSecret.SecretArn" `
            --output text
    }
    if (-not $databaseSecretArn -or $databaseSecretArn -eq "None") {
        throw "Restored database has no destination-managed master secret."
    }
    $foundation.DatabaseSecretArn = $databaseSecretArn.Trim()
    Write-Host "Granting the ECS execution role access to the exact restored database secret..."
    Invoke-Aws cloudformation deploy `
        --template-file (Join-Path $ProjectRoot "infra\aws\demo-foundation.yaml") `
        --stack-name $FoundationStack `
        --region $Region `
        --capabilities CAPABILITY_NAMED_IAM `
        --parameter-overrides `
            "OpenAiApiKeySecretArn=$openAiSecretArn" `
            "DatabaseInstanceIdentifier=$DatabaseInstanceIdentifier" `
            "DatabaseSnapshotIdentifier=$DatabaseSnapshotIdentifier" `
            "RestoredDatabaseSecretArn=$($foundation.DatabaseSecretArn)" `
            "CloudFrontOriginPrefixListId=$cloudFrontOriginPrefixListId" `
        --no-fail-on-empty-changeset `
        --tags Project=ai-financial-wellness-coach Environment=demo
}
if ($ExistingOidcIssuerUrl) {
    if (-not $ExistingOidcClientId -or -not $ExistingOidcRedirectUri) {
        throw "Existing Cognito sign-in requires issuer, client ID, and redirect URI."
    }
    $issuer = $ExistingOidcIssuerUrl.TrimEnd("/")
    $foundation.OidcIssuerUrl = $issuer
    $foundation.OidcJwksUrl = "$issuer/.well-known/jwks.json"
    $foundation.OidcServerMetadataUrl = "$issuer/.well-known/openid-configuration"
    $foundation.OidcClientId = $ExistingOidcClientId
    $foundation.OidcRedirectUri = $ExistingOidcRedirectUri
    $foundation.OidcUserPoolId = $issuer.Split("/")[-1]
}
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
    "CloudFrontOriginSecretArn=$($foundation.CloudFrontOriginSecretArn)",
    "FrontendUrl=$($foundation.FrontendUrl)",
    "OidcIssuerUrl=$($foundation.OidcIssuerUrl)",
    "OidcLegacyIssuerUrl=$LegacyCognitoIssuerUrl",
    "OidcJwksUrl=$($foundation.OidcJwksUrl)",
    "OidcClientId=$($foundation.OidcClientId)",
    "OidcServerMetadataUrl=$($foundation.OidcServerMetadataUrl)",
    "OidcRedirectUri=$($foundation.OidcRedirectUri)",
    "FrontendOidcCookieSecretArn=$($foundation.FrontendOidcCookieSecretArn)",
    "EcsClusterName=$($foundation.EcsClusterName)",
    "ServiceDiscoveryNamespaceId=$($foundation.ServiceDiscoveryNamespaceId)",
    "TaskExecutionRoleArn=$($foundation.TaskExecutionRoleArn)",
    "AppTaskRoleArn=$($foundation.AppTaskRoleArn)",
    "AiTaskRoleArn=$($foundation.AiTaskRoleArn)",
    "BackendApiKeySecretArn=$($foundation.BackendApiKeySecretArn)",
    "AiServiceApiKeySecretArn=$($foundation.AiServiceApiKeySecretArn)",
    "OpenAiApiKeySecretArn=$($foundation.OpenAiApiKeySecretArn)",
    "DatabaseEndpoint=$($foundation.DatabaseEndpoint)",
    "DatabasePort=$($foundation.DatabasePort)",
    "DatabaseName=$($foundation.DatabaseName)",
    "DatabaseSecretArn=$($foundation.DatabaseSecretArn)",
    "AiLogGroupName=$($foundation.AiLogGroupName)",
    "BackendLogGroupName=$($foundation.BackendLogGroupName)",
    "FrontendLogGroupName=$($foundation.FrontendLogGroupName)",
    "EducationCorpusVersion=$EducationCorpusVersion",
    "PolicyCorpusVersion=$PolicyCorpusVersion",
    "OpenAiModelId=$OpenAiModelId",
    "AlertEmail=$AlertEmail",
    "AiImageUri=$($images.Ai)",
    "BackendImageUri=$($images.Backend)",
    "FrontendImageUri=$($images.Frontend)"
)
if ($EnableDatabaseCredentialRefresh) {
    if (-not $foundation.BackendTaskRoleArn) {
        throw "The foundation must provide the dedicated BackendTaskRoleArn."
    }
    $applicationParameters += "BackendTaskRoleArn=$($foundation.BackendTaskRoleArn)"
}
Invoke-Aws cloudformation deploy `
    --template-file (Join-Path $ProjectRoot "infra\aws\demo-application.yaml") `
    --stack-name $ApplicationStack `
    --region $Region `
    --parameter-overrides @applicationParameters `
    --no-fail-on-empty-changeset `
    --tags Project=ai-financial-wellness-coach Environment=demo

$application = Get-StackOutputs $ApplicationStack

Write-Host "Running initial database migration as a one-shot ECS task..."
$migrationNetwork = "awsvpcConfiguration={subnets=[$($foundation.PublicSubnetAId),$($foundation.PublicSubnetBId)],securityGroups=[$($foundation.BackendSecurityGroupId)],assignPublicIp=ENABLED}"
$migrationOverrides = @{
    containerOverrides = @(
        @{
            name = $application.BackendContainerName
            command = @("alembic", "upgrade", "head")
        }
    )
} | ConvertTo-Json -Depth 5 -Compress
$migrationTaskArn = Invoke-Aws ecs run-task `
    --cluster $foundation.EcsClusterName `
    --task-definition $application.BackendTaskFamily `
    --launch-type FARGATE `
    --network-configuration $migrationNetwork `
    --overrides $migrationOverrides `
    --region $Region `
    --query "tasks[0].taskArn" `
    --output text
if (-not $migrationTaskArn -or $migrationTaskArn -eq "None") {
    throw "ECS did not start the initial database migration task."
}
Invoke-Aws ecs wait tasks-stopped `
    --cluster $foundation.EcsClusterName `
    --tasks $migrationTaskArn `
    --region $Region
$migrationExitCode = Invoke-Aws ecs describe-tasks `
    --cluster $foundation.EcsClusterName `
    --tasks $migrationTaskArn `
    --region $Region `
    --query "tasks[0].containers[?name=='$($application.BackendContainerName)'].exitCode | [0]" `
    --output text
if ($migrationExitCode -ne "0") {
    throw "Initial database migration failed with exit code $migrationExitCode."
}

# Keep a provider created by this stack under CloudFormation ownership. Only pass an
# existing ARN when the provider is genuinely external to the OIDC stack.
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
    "EcsBackendTaskFamily=$($application.BackendTaskFamily)",
    "EcsTaskExecutionRoleArn=$($foundation.TaskExecutionRoleArn)",
    "EcsAppTaskRoleArn=$($foundation.AppTaskRoleArn)",
    "EcsAiTaskRoleArn=$($foundation.AiTaskRoleArn)",
    "OperationalAlertsTopicArn=$($application.OperationalAlertsTopicArn)"
)
if ($foundation.BackendTaskRoleArn) {
    $oidcParameters += "EcsBackendTaskRoleArn=$($foundation.BackendTaskRoleArn)"
}
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
    FrontendUrl = $foundation.FrontendUrl
    OidcUserPoolId = $foundation.OidcUserPoolId
    OidcClientId = $foundation.OidcClientId
    PublishRoleArn = $oidc.PublishRoleArn
    DeployRoleArn = $oidc.DeployRoleArn
    BootstrapTag = $bootstrapTag
}
$summary | ConvertTo-Json
