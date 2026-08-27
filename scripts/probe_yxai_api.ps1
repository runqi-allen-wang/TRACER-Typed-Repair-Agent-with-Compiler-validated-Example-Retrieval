[CmdletBinding()]
param(
  [string]$ApiUrl = "https://yxai.chat/v1/responses",
  [string]$Model = "gpt-5.6-sol",
  [ValidateRange(1, 4096)]
  [int]$MaxOutputTokens = 64,
  [ValidateRange(1, 300)]
  [int]$TimeoutSec = 120,
  [string]$ResultPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$keyPtr = [IntPtr]::Zero
$plainKey = $null
$response = $null
$startedAt = [Diagnostics.Stopwatch]::StartNew()

function Save-ProbeResult {
  param([hashtable]$Result)
  if (-not [string]::IsNullOrWhiteSpace($ResultPath)) {
    $parent = Split-Path -Parent $ResultPath
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
      New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $Result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
  }
}

function Read-OptionalProperty {
  param(
    [object]$Object,
    [string]$Name
  )
  if ($null -eq $Object) { return $null }
  $property = $Object.PSObject.Properties[$Name]
  if ($null -eq $property) { return $null }
  return $property.Value
}

try {
  $secureKey = Read-Host "Enter yxai API Key (input is hidden)" -AsSecureString
  if ($secureKey.Length -eq 0) {
    throw "API Key cannot be empty"
  }

  $keyPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
  $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPtr)
  $headers = @{ Authorization = "Bearer $plainKey" }
  $payload = @{
    model = $Model
    input = "Reply with exactly OK."
    max_output_tokens = $MaxOutputTokens
    store = $false
    reasoning = @{ effort = "high" }
  } | ConvertTo-Json -Depth 4 -Compress

  try {
    $response = Invoke-RestMethod `
      -Uri $ApiUrl `
      -Method Post `
      -Headers $headers `
      -ContentType "application/json" `
      -Body $payload `
      -TimeoutSec $TimeoutSec `
      -MaximumRedirection 0
  }
  catch {
    $statusCode = $null
    if ($null -ne $_.Exception.Response) {
      try { $statusCode = [int]$_.Exception.Response.StatusCode } catch { $statusCode = $null }
    }
    $startedAt.Stop()
    $failure = @{
      ok = $false
      tested_at_utc = (Get-Date).ToUniversalTime().ToString("o")
      endpoint = $ApiUrl
      model = $Model
      wire_api = "responses"
      store = $false
      reasoning_effort = "high"
      http_status = $statusCode
      error_type = $_.Exception.GetType().FullName
      elapsed_ms = $startedAt.ElapsedMilliseconds
    }
    Save-ProbeResult $failure
    Write-Host "yxai API probe failed." -ForegroundColor Red
    Write-Host "HTTP status: $statusCode"
    Write-Host "No response body or credential was saved."
    Start-Sleep -Seconds 3
    exit 1
  }

  $outputText = [string](Read-OptionalProperty $response "output_text")
  if ([string]::IsNullOrWhiteSpace($outputText)) {
    $outputItems = Read-OptionalProperty $response "output"
    foreach ($item in @($outputItems)) {
      if ((Read-OptionalProperty $item "type") -ne "message") { continue }
      foreach ($content in @(Read-OptionalProperty $item "content")) {
        if ((Read-OptionalProperty $content "type") -eq "output_text") {
          $outputText += [string](Read-OptionalProperty $content "text")
        }
      }
    }
  }
  if (-not [string]::IsNullOrEmpty($plainKey) -and $outputText.Contains($plainKey)) {
    throw "Provider response reflected the credential"
  }

  $usage = Read-OptionalProperty $response "usage"
  $startedAt.Stop()
  $success = @{
    ok = $true
    tested_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    endpoint = $ApiUrl
    model = $Model
    wire_api = "responses"
    store = $false
    reasoning_effort = "high"
    http_status = "2xx"
    output_received = -not [string]::IsNullOrWhiteSpace($outputText)
    output_exact_ok = $outputText.Trim() -eq "OK"
    input_tokens = Read-OptionalProperty $usage "input_tokens"
    output_tokens = Read-OptionalProperty $usage "output_tokens"
    total_tokens = Read-OptionalProperty $usage "total_tokens"
    elapsed_ms = $startedAt.ElapsedMilliseconds
  }
  Save-ProbeResult $success
  Write-Host "yxai API probe succeeded." -ForegroundColor Green
  Write-Host ("Model: " + $Model)
  Write-Host ("Output received: " + $success.output_received)
  Write-Host ("Elapsed ms: " + $success.elapsed_ms)
  Write-Host "No response body or credential was saved."
  Start-Sleep -Seconds 3
  exit 0
}
catch {
  $startedAt.Stop()
  $failure = @{
    ok = $false
    tested_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    endpoint = $ApiUrl
    model = $Model
    wire_api = "responses"
    store = $false
    reasoning_effort = "high"
    http_status = $null
    error_type = $_.Exception.GetType().FullName
    elapsed_ms = $startedAt.ElapsedMilliseconds
  }
  Save-ProbeResult $failure
  Write-Host "yxai API probe failed before a valid response was received." -ForegroundColor Red
  Write-Host ("Error type: " + $failure.error_type)
  Write-Host "No response body or credential was saved."
  Start-Sleep -Seconds 3
  exit 1
}
finally {
  $response = $null
  $headers = $null
  $payload = $null
  $plainKey = $null
  if ($keyPtr -ne [IntPtr]::Zero) {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPtr)
    $keyPtr = [IntPtr]::Zero
  }
  Remove-Variable secureKey, plainKey, headers, payload, response -ErrorAction SilentlyContinue
}
