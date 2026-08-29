param(
    [string]$AccountId = "902552928492",
    [string]$Region = "ap-southeast-1",
    [string]$Repository = "Seanleng99/nus-iss-ais-team9",
    [string]$FoundationStack = "ai-financial-wellness-coach-foundation",
    [string]$ApplicationStack = "ai-financial-wellness-coach-application",
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$ExpectedReleaseSha,
    [string]$ExpectedFrontendReleaseSha = "",
    [string]$CustomDomainName = "",
    [string]$CustomDomainHostedZoneId = "",
    [string]$CloudFrontViewerCertificateArn = "",
    [string]$OriginDomainName = "",
    [string]$OriginCertificateArn = "",
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

function Get-ServiceImage {
    param([string]$ClusterName, [string]$ServiceName, [string]$ContainerName)
    $taskDefinition = Invoke-Aws ecs describe-services `
        --cluster $ClusterName `
        --services $ServiceName `
        --region $Region `
        --query "services[0].taskDefinition" `
        --output text
    if (-not $taskDefinition -or $taskDefinition -eq "None") {
        throw "Could not resolve the stable task definition for $ServiceName."
    }
    $image = Invoke-Aws ecs describe-task-definition `
        --task-definition $taskDefinition `
        --region $Region `
        --query "taskDefinition.containerDefinitions[?name=='$ContainerName'].image | [0]" `
        --output text
    if (-not $image -or $image -eq "None") {
        throw "Could not resolve container $ContainerName in $taskDefinition."
    }
    return $image
}

function Test-CertificateName {
    param([object]$Certificate, [string]$DomainName)
    $candidate = $DomainName.ToLowerInvariant()
    $names = @($Certificate.DomainName) + @($Certificate.SubjectAlternativeNames)
    foreach ($name in $names) {
        $pattern = ([string]$name).ToLowerInvariant()
        if ($pattern -eq $candidate) {
            return $true
        }
        if ($pattern.StartsWith("*.")) {
            $suffix = $pattern.Substring(1)
            if ($candidate.EndsWith($suffix)) {
                $prefix = $candidate.Substring(0, $candidate.Length - $suffix.Length)
                if ($prefix -and -not $prefix.Contains(".")) {
                    return $true
                }
            }
        }
    }
    return $false
}

function Assert-Certificate {
    param(
        [string]$CertificateArn,
        [string]$CertificateRegion,
        [string]$DomainName,
        [string]$Purpose
    )
    $certificate = Invoke-Aws acm describe-certificate `
        --certificate-arn $CertificateArn `
        --region $CertificateRegion `
        --query "Certificate" `
        --output json | ConvertFrom-Json
    if ($certificate.Status -ne "ISSUED") {
        throw "$Purpose certificate must be ISSUED; received $($certificate.Status)."
    }
    if (-not (Test-CertificateName $certificate $DomainName)) {
        throw "$Purpose certificate does not cover $DomainName."
    }
}

function Deploy-Application {
    param(
        [hashtable]$Foundation,
        [string]$AiImage,
        [string]$BackendImage,
        [string]$FrontendImage,
        [string]$RegionalOriginCertificateArn
    )
    $parameters = @(
        "AiServiceImageUri=$AiImage",
        "BackendImageUri=$BackendImage",
        "FrontendImageUri=$FrontendImage",
        "CloudFrontOriginSecretArn=$($Foundation.CloudFrontOriginSecretArn)",
        "FrontendUrl=$($Foundation.FrontendUrl)",
        "OidcIssuerUrl=$($Foundation.OidcIssuerUrl)",
        "OidcJwksUrl=$($Foundation.OidcJwksUrl)",
        "OidcClientId=$($Foundation.OidcClientId)",
        "OidcServerMetadataUrl=$($Foundation.OidcServerMetadataUrl)",
        "OidcRedirectUri=$($Foundation.OidcRedirectUri)",
        "FrontendOidcCookieSecretArn=$($Foundation.FrontendOidcCookieSecretArn)"
    )
    if ($RegionalOriginCertificateArn) {
        $parameters += "OriginCertificateArn=$RegionalOriginCertificateArn"
    }
    Invoke-Aws cloudformation deploy `
        --template-file (Join-Path $ProjectRoot "infra\aws\demo-application.yaml") `
        --stack-name $ApplicationStack `
        --region $Region `
        --parameter-overrides @parameters `
        --no-fail-on-empty-changeset `
        --tags Project=ai-financial-wellness-coach Environment=demo
}

if ($Confirmation -cne "HARDEN-EDGE") {
    throw "Pass -Confirmation HARDEN-EDGE to change the public application boundary."
}
if (-not $ExpectedFrontendReleaseSha) {
    $ExpectedFrontendReleaseSha = $ExpectedReleaseSha
}
if ($ExpectedFrontendReleaseSha -notmatch "^[0-9a-f]{40}$") {
    throw "ExpectedFrontendReleaseSha must be a lowercase 40-character Git SHA."
}

$customValues = @(
    $CustomDomainName,
    $CustomDomainHostedZoneId,
    $CloudFrontViewerCertificateArn,
    $OriginDomainName,
    $OriginCertificateArn
)
$customDomainRequested = [bool]($customValues | Where-Object { $_ })
if ($customDomainRequested -and ($customValues | Where-Object { -not $_ })) {
    throw "Custom-domain activation requires both DNS names, the hosted zone, and both ACM certificate ARNs."
}
if ($customDomainRequested -and $CustomDomainName -eq $OriginDomainName) {
    throw "CustomDomainName and OriginDomainName must be different DNS names."
}

$identity = Invoke-Aws sts get-caller-identity --output json | ConvertFrom-Json
if ($identity.Account -ne $AccountId) {
    throw "Authenticated AWS account $($identity.Account) does not match expected account $AccountId."
}

$foundationBefore = Get-StackOutputs $FoundationStack
$applicationBefore = Get-StackOutputs $ApplicationStack
if (-not $applicationBefore.EducationKnowledgeBaseId -or -not $applicationBefore.PolicyKnowledgeBaseId) {
    throw "The application stack must expose both governed Knowledge Base IDs."
}

Invoke-Aws ecs wait services-stable `
    --cluster $foundationBefore.EcsClusterName `
    --services `
        $applicationBefore.AiServiceName `
        $applicationBefore.BackendServiceName `
        $applicationBefore.FrontendServiceName `
    --region $Region
$aiImage = Get-ServiceImage `
    $foundationBefore.EcsClusterName $applicationBefore.AiServiceName $applicationBefore.AiContainerName
$backendImage = Get-ServiceImage `
    $foundationBefore.EcsClusterName $applicationBefore.BackendServiceName $applicationBefore.BackendContainerName
$frontendImage = Get-ServiceImage `
    $foundationBefore.EcsClusterName $applicationBefore.FrontendServiceName $applicationBefore.FrontendContainerName
if (-not $backendImage.EndsWith(":$ExpectedReleaseSha")) {
    throw "The deployed backend image '$backendImage' does not match release $ExpectedReleaseSha."
}
if (-not $frontendImage.EndsWith(":$ExpectedFrontendReleaseSha")) {
    throw "The deployed frontend image '$frontendImage' does not match release $ExpectedFrontendReleaseSha."
}

$cloudFrontOriginPrefixListId = Invoke-Aws ec2 describe-managed-prefix-lists `
    --filters "Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing" `
    --region $Region `
    --query "PrefixLists[0].PrefixListId" `
    --output text
if (-not $cloudFrontOriginPrefixListId -or $cloudFrontOriginPrefixListId -eq "None") {
    throw "The regional CloudFront origin-facing managed prefix list was not found."
}

if ($customDomainRequested) {
    Assert-Certificate `
        $CloudFrontViewerCertificateArn "us-east-1" $CustomDomainName "CloudFront viewer"
    Assert-Certificate `
        $OriginCertificateArn $Region $OriginDomainName "ALB origin"
    $hostedZone = Invoke-Aws route53 get-hosted-zone `
        --id $CustomDomainHostedZoneId `
        --query "{Name:HostedZone.Name,Private:HostedZone.Config.PrivateZone}" `
        --output json | ConvertFrom-Json
    if ($hostedZone.Private) {
        throw "CustomDomainHostedZoneId must identify a public Route 53 hosted zone."
    }
    $zoneName = ([string]$hostedZone.Name).TrimEnd(".").ToLowerInvariant()
    foreach ($domain in @($CustomDomainName, $OriginDomainName)) {
        if ($domain -ne $zoneName -and -not $domain.EndsWith(".$zoneName")) {
            throw "$domain is not contained by hosted zone $zoneName."
        }
    }
}

Write-Host "Applying CloudFront managed-prefix and origin-header restrictions..."
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
if (-not $foundation.CloudFrontOriginSecretArn) {
    throw "The foundation stack did not expose the CloudFront origin secret ARN."
}

if ($customDomainRequested) {
    Write-Host "Preparing the HTTPS origin listener before switching CloudFront..."
}
Deploy-Application `
    $foundation $aiImage $backendImage $frontendImage $OriginCertificateArn

if ($customDomainRequested) {
    Write-Host "Activating the custom CloudFront domain and HTTPS origin..."
    Invoke-Aws cloudformation deploy `
        --template-file (Join-Path $ProjectRoot "infra\aws\demo-foundation.yaml") `
        --stack-name $FoundationStack `
        --region $Region `
        --capabilities CAPABILITY_NAMED_IAM `
        --parameter-overrides `
            "EducationKnowledgeBaseId=$($applicationBefore.EducationKnowledgeBaseId)" `
            "PolicyKnowledgeBaseId=$($applicationBefore.PolicyKnowledgeBaseId)" `
            "CloudFrontOriginPrefixListId=$cloudFrontOriginPrefixListId" `
            "CustomDomainName=$CustomDomainName" `
            "CustomDomainHostedZoneId=$CustomDomainHostedZoneId" `
            "CloudFrontViewerCertificateArn=$CloudFrontViewerCertificateArn" `
            "OriginDomainName=$OriginDomainName" `
        --no-fail-on-empty-changeset `
        --tags Project=ai-financial-wellness-coach Environment=demo
    $foundation = Get-StackOutputs $FoundationStack
    Deploy-Application `
        $foundation $aiImage $backendImage $frontendImage $OriginCertificateArn
}

Invoke-Aws ecs wait services-stable `
    --cluster $foundation.EcsClusterName `
    --services `
        $applicationBefore.AiServiceName `
        $applicationBefore.BackendServiceName `
        $applicationBefore.FrontendServiceName `
    --region $Region

$validationArguments = @(
    (Join-Path $ProjectRoot "infra\scripts\edge_security_validation.py"),
    "--frontend-url",
    $foundation.FrontendUrl,
    "--origin-url",
    "http://$($foundation.LoadBalancerDnsName)"
)
if ($customDomainRequested) {
    $validationArguments += @("--expected-custom-domain", $CustomDomainName)
}
& python @validationArguments
if ($LASTEXITCODE -ne 0) {
    throw "Edge security validation failed."
}

& (Join-Path $PSScriptRoot "configure_github.ps1") `
    -Repository $Repository `
    -Region $Region `
    -FoundationStack $FoundationStack `
    -ApplicationStack $ApplicationStack

[ordered]@{
    FrontendUrl = $foundation.FrontendUrl
    LoadBalancerDnsName = $foundation.LoadBalancerDnsName
    OriginRestrictionEnabled = $foundation.OriginRestrictionEnabled
    CustomDomainEnabled = $foundation.CustomDomainEnabled
    OriginProtocol = $foundation.OriginProtocol
    ViewerTlsPolicy = $foundation.ViewerTlsPolicy
} | ConvertTo-Json
