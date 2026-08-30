param(
    [string]$AccountId = "902552928492",
    [string]$Region = "ap-southeast-1",
    [string]$ApplicationStack = "ai-financial-wellness-coach-application",
    [string]$AlarmName = "ai-financial-wellness-coach-demo-backend-5xx",
    [string]$ExpectedEndpoint = "",
    [string]$EvidencePath = "artifacts/operational-alert-test.json",
    [string]$Confirmation = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Aws = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"

if ($Confirmation -cne "TEST-OPERATIONAL-ALERT") {
    throw "Pass -Confirmation TEST-OPERATIONAL-ALERT to exercise the CloudWatch-to-SNS notification path."
}
if (-not (Test-Path -LiteralPath $Aws)) {
    throw "AWS CLI was not found at $Aws"
}

function Invoke-Aws {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $output = & $Aws @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "AWS CLI command failed: aws $($Arguments -join ' ')"
    }
    return $output
}

function Wait-AlarmState {
    param([string]$ExpectedState)
    foreach ($attempt in 1..15) {
        $state = Invoke-Aws cloudwatch describe-alarms `
            --alarm-names $AlarmName `
            --region $Region `
            --query "MetricAlarms[0].StateValue" `
            --output text
        if ($state -eq $ExpectedState) {
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "$AlarmName did not enter $ExpectedState within 30 seconds."
}

$identity = Invoke-Aws sts get-caller-identity --output json | ConvertFrom-Json
if ($identity.Account -ne $AccountId) {
    throw "Authenticated AWS account $($identity.Account) does not match expected account $AccountId."
}

$stack = Invoke-Aws cloudformation describe-stacks `
    --stack-name $ApplicationStack `
    --region $Region `
    --query "Stacks[0]" `
    --output json | ConvertFrom-Json
$topicArn = ($stack.Outputs | Where-Object {
    $_.OutputKey -eq "OperationalAlertsTopicArn"
}).OutputValue
if (-not $topicArn) {
    throw "$ApplicationStack does not expose OperationalAlertsTopicArn."
}

$subscriptionResponse = Invoke-Aws sns list-subscriptions-by-topic `
    --topic-arn $topicArn `
    --region $Region `
    --output json | ConvertFrom-Json
$confirmedSubscriptions = @($subscriptionResponse.Subscriptions | Where-Object {
    $_.Protocol -eq "email" -and
    $_.SubscriptionArn -ne "PendingConfirmation" -and
    $_.SubscriptionArn -ne "Deleted"
})
if ($confirmedSubscriptions.Count -eq 0) {
    throw "No confirmed email subscription exists for the operational alert topic."
}
if ($ExpectedEndpoint -and
    $confirmedSubscriptions.Endpoint -notcontains $ExpectedEndpoint) {
    throw "The expected operational email endpoint is not confirmed."
}

$alarm = Invoke-Aws cloudwatch describe-alarms `
    --alarm-names $AlarmName `
    --region $Region `
    --query "MetricAlarms[0]" `
    --output json | ConvertFrom-Json
if (-not $alarm.AlarmName) {
    throw "Operational alarm $AlarmName was not found."
}
if ($alarm.AlarmActions -notcontains $topicArn) {
    throw "$AlarmName does not route ALARM actions to the operational SNS topic."
}
if ($alarm.StateValue -eq "ALARM") {
    throw "$AlarmName is already in ALARM. Investigate the real alarm before running a notification test."
}

$testId = [guid]::NewGuid().ToString()
$startedAt = [DateTime]::UtcNow
$startedAtText = $startedAt.ToString("o")
$originalState = $alarm.StateValue
$testReason = "Controlled operational notification test $testId"
$testReasonData = @{
    kind = "controlled-operational-notification-test"
    test_id = $testId
} | ConvertTo-Json -Compress
$testStateApplied = $false

try {
    Invoke-Aws cloudwatch set-alarm-state `
        --alarm-name $AlarmName `
        --state-value ALARM `
        --state-reason $testReason `
        --state-reason-data $testReasonData `
        --region $Region | Out-Null
    $testStateApplied = $true
    Wait-AlarmState "ALARM"

    $actionExecuted = $false
    $actionTimestamp = $null
    foreach ($attempt in 1..15) {
        $history = Invoke-Aws cloudwatch describe-alarm-history `
            --alarm-name $AlarmName `
            --history-item-type Action `
            --start-date $startedAtText `
            --region $Region `
            --query "AlarmHistoryItems" `
            --output json | ConvertFrom-Json
        $topicActions = @($history | Where-Object {
            $_.HistorySummary -like "*action*$topicArn*"
        }) | Sort-Object Timestamp -Descending
        $failedAction = $topicActions | Where-Object {
            $_.HistorySummary -like "Failed to execute action*"
        } | Select-Object -First 1
        if ($failedAction) {
            $failure = $failedAction.HistoryData | ConvertFrom-Json
            throw "CloudWatch alarm action failed: $($failure.error)"
        }
        $successfulAction = $topicActions | Where-Object {
            $_.HistorySummary -like "Successfully executed action*"
        } | Select-Object -First 1
        if ($successfulAction) {
            $actionExecuted = $true
            $actionTimestamp = ([DateTime]$successfulAction.Timestamp).ToUniversalTime().ToString("o")
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $actionExecuted) {
        throw "CloudWatch did not record successful execution of the SNS alarm action within 30 seconds."
    }
}
finally {
    if ($testStateApplied) {
        Invoke-Aws cloudwatch set-alarm-state `
            --alarm-name $AlarmName `
            --state-value $originalState `
            --state-reason "Restored after controlled operational notification test $testId" `
            --region $Region | Out-Null
        Wait-AlarmState $originalState
    }
}

$completedAt = [DateTime]::UtcNow
$evidence = [ordered]@{
    schema_version = "1.0"
    test_id = $testId
    started_at_utc = $startedAtText
    completed_at_utc = $completedAt.ToString("o")
    account_id = $identity.Account
    region = $Region
    application_stack = $ApplicationStack
    alarm_name = $AlarmName
    original_alarm_state = $originalState
    restored_alarm_state = $originalState
    topic_arn = $topicArn
    confirmed_email_subscription_count = $confirmedSubscriptions.Count
    expected_endpoint_confirmed = [bool]$ExpectedEndpoint
    cloudwatch_sns_action_executed = $actionExecuted
    cloudwatch_sns_action_timestamp_utc = $actionTimestamp
    human_delivery_acknowledgement = "required-separately"
}

$resolvedEvidencePath = if ([IO.Path]::IsPathRooted($EvidencePath)) {
    $EvidencePath
} else {
    Join-Path $ProjectRoot $EvidencePath
}
$evidenceDirectory = Split-Path -Parent $resolvedEvidencePath
New-Item -ItemType Directory -Path $evidenceDirectory -Force | Out-Null
$evidence | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $resolvedEvidencePath

Write-Host "CloudWatch invoked the confirmed SNS notification path successfully."
Write-Host "Evidence: $resolvedEvidencePath"
Write-Host "A human recipient must still acknowledge receipt before delivery is marked verified."
