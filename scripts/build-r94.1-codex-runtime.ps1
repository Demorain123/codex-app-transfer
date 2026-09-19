param(
    [switch]$PreflightOnly,
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $RepoRoot 'target\release\codex-r94.1-runtime.exe'
}

$PatchRevision = 'r94.1-openai-policy-v2'
$PatchMarker = 'CAS-R94-1-BUILTIN-OPENAI-POLICY-OVERLAY'
$PatchTestMarker = 'CAS-R94-1-BUILTIN-OPENAI-POLICY-OVERLAY-TEST'
$PatchTest = @'

#[test]
fn r94_1_builtin_openai_policy_overlay_reuses_retry_without_identity_change() {
    // CAS-R94-1-BUILTIN-OPENAI-POLICY-OVERLAY-TEST
    unsafe {
        std::env::set_var("CAS_R94_1_OPENAI_POLICY_OVERLAY", "1");
    }

    let configured = ModelProviderInfo {
        name: "User OpenAi".to_string(),
        base_url: Some("https://must-not-win.example/v1".to_string()),
        request_max_retries: Some(7),
        stream_max_retries: Some(15),
        stream_idle_timeout_ms: Some(90_000),
        websocket_connect_timeout_ms: Some(12_000),
        ..ModelProviderInfo::default()
    };
    let merged = merge_configured_model_providers(
        built_in_model_providers(Some("http://127.0.0.1:18080".to_string())),
        std::collections::HashMap::from([(
            OPENAI_PROVIDER_ID.to_string(),
            configured,
        )]),
    )
    .expect("r94.1 overlay merge should succeed");

    unsafe {
        std::env::remove_var("CAS_R94_1_OPENAI_POLICY_OVERLAY");
    }

    let openai = merged
        .get(OPENAI_PROVIDER_ID)
        .expect("built-in openai must remain present");
    assert_eq!(openai.base_url.as_deref(), Some("http://127.0.0.1:18080"));
    assert_ne!(openai.name, "User OpenAi");
    assert_eq!(openai.request_max_retries, Some(7));
    assert_eq!(openai.stream_max_retries, Some(15));
    assert_eq!(openai.stream_idle_timeout_ms, Some(90_000));
    assert_eq!(openai.websocket_connect_timeout_ms, Some(12_000));
}
'@
$MergeAnchor = @'
        } else {
            model_providers.entry(key).or_insert(provider);
        }
'@
$MergeReplacement = @'
        } else if key == OPENAI_PROVIDER_ID
            && std::env::var_os("CAS_R94_1_OPENAI_POLICY_OVERLAY").is_some()
        {
            // CAS-R94-1-BUILTIN-OPENAI-POLICY-OVERLAY
            //
            // Transfer keeps the effective provider id as the built-in "openai".
            // Only portable behavior fields are merged from the configured
            // [model_providers.openai] overlay. Identity/routing/auth fields are
            // deliberately ignored so provider identity and ChatGPT auth remain
            // exactly the upstream built-in OpenAI path.
            if let Some(built_in_provider) = model_providers.get_mut(&key) {
                if let Some(query_params) = provider.query_params.take() {
                    built_in_provider.query_params = Some(query_params);
                }
                if let Some(http_headers) = provider.http_headers.take() {
                    built_in_provider
                        .http_headers
                        .get_or_insert_default()
                        .extend(http_headers);
                }
                if let Some(env_http_headers) = provider.env_http_headers.take() {
                    built_in_provider
                        .env_http_headers
                        .get_or_insert_default()
                        .extend(env_http_headers);
                }
                if provider.request_max_retries.is_some() {
                    built_in_provider.request_max_retries = provider.request_max_retries;
                }
                if provider.stream_max_retries.is_some() {
                    built_in_provider.stream_max_retries = provider.stream_max_retries;
                }
                if provider.stream_idle_timeout_ms.is_some() {
                    built_in_provider.stream_idle_timeout_ms = provider.stream_idle_timeout_ms;
                }
                if provider.websocket_connect_timeout_ms.is_some() {
                    built_in_provider.websocket_connect_timeout_ms =
                        provider.websocket_connect_timeout_ms;
                }
            }
        } else {
            model_providers.entry(key).or_insert(provider);
        }
'@

if ($PreflightOnly) {
    foreach ($Marker in @(
        $PatchMarker,
        'CAS_R94_1_OPENAI_POLICY_OVERLAY',
        'provider.stream_max_retries.is_some()',
        'built_in_provider.stream_max_retries = provider.stream_max_retries',
        'provider.request_max_retries.is_some()',
        'provider.stream_idle_timeout_ms.is_some()',
        'provider.websocket_connect_timeout_ms.is_some()',
        'provider.http_headers.take()',
        'provider.query_params.take()'
    )) {
        if (-not $MergeReplacement.Contains($Marker)) {
            throw "r94.1 Codex runtime patch contract missing: $Marker"
        }
    }
    foreach ($Marker in @(
        $PatchTestMarker,
        'assert_eq!(openai.stream_max_retries, Some(15))',
        'assert_eq!(openai.request_max_retries, Some(7))',
        'assert_eq!(openai.base_url.as_deref(), Some("http://127.0.0.1:18080"))',
        'assert_ne!(openai.name, "User OpenAi")'
    )) {
        if (-not $PatchTest.Contains($Marker)) {
            throw "r94.1 Codex runtime patch test contract missing: $Marker"
        }
    }
    if ($MergeReplacement.Contains('built_in_provider.base_url') -or
        $MergeReplacement.Contains('built_in_provider.requires_openai_auth') -or
        $MergeReplacement.Contains('built_in_provider.name =')) {
        throw 'r94.1 Codex runtime patch must not override built-in openai identity/routing/auth'
    }
    Write-Host 'R94_1_CODEX_RUNTIME_PATCH_PREFLIGHT_PASS' -ForegroundColor Green
    return
}

if (-not $IsWindows) {
    throw 'r94.1 patched Codex runtime build currently supports Windows preview builds only'
}

$Package = Get-AppxPackage -Name 'OpenAI.Codex' |
    Sort-Object Version -Descending |
    Select-Object -First 1
if ($null -eq $Package -or [string]::IsNullOrWhiteSpace($Package.InstallLocation)) {
    throw 'OpenAI.Codex AppX package not found; cannot pin the r94.1 runtime patch to the installed Desktop runtime'
}

$Candidates = @(
    Get-ChildItem -LiteralPath $Package.InstallLocation -Recurse -File -Filter 'codex.exe' -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '(?i)\\app\\codex\.exe$' }
)

$BundledRuntime = $null
$CodexCliVersion = $null
foreach ($Candidate in $Candidates) {
    try {
        $VersionText = (& $Candidate.FullName --version 2>$null | Out-String).Trim()
    } catch {
        continue
    }
    if ($VersionText -match '(?i)^codex-cli\s+([0-9]+\.[0-9]+\.[0-9]+(?:[-+][^\s]+)?)') {
        $BundledRuntime = $Candidate.FullName
        $CodexCliVersion = $Matches[1]
        break
    }
}
if ($null -eq $BundledRuntime -or [string]::IsNullOrWhiteSpace($CodexCliVersion)) {
    throw "could not locate the bundled codex-cli runtime under $($Package.InstallLocation)"
}

$Tag = "rust-v$CodexCliVersion"
$WorkRoot = Join-Path $RepoRoot 'target\r94.1-codex-runtime'
$SourceDir = Join-Path $WorkRoot "src-$CodexCliVersion"
$BuildTarget = Join-Path $WorkRoot "build-$CodexCliVersion"
$MetadataPath = "$OutputPath.json"

$Reuse = $false
if ((Test-Path -LiteralPath $OutputPath) -and (Test-Path -LiteralPath $MetadataPath)) {
    try {
        $Metadata = Get-Content -LiteralPath $MetadataPath -Raw | ConvertFrom-Json
        $BuiltVersion = (& $OutputPath --version 2>$null | Out-String).Trim()
        $VersionPattern = [regex]::Escape($CodexCliVersion)
        $Reuse =
            $Metadata.patchRevision -eq $PatchRevision -and
            $Metadata.upstreamTag -eq $Tag -and
            $Metadata.codexCliVersion -eq $CodexCliVersion -and
            $BuiltVersion -match "(?i)^codex-cli\s+$VersionPattern(?:\s|$)"
    } catch {
        $Reuse = $false
    }
}

if (-not $Reuse) {
    New-Item -ItemType Directory -Force -Path $WorkRoot | Out-Null
    if (Test-Path -LiteralPath $SourceDir) {
        Remove-Item -LiteralPath $SourceDir -Recurse -Force
    }

    Write-Host "[r94.1] cloning openai/codex $Tag for the version-matched runtime patch"
    git clone --filter=blob:none --depth 1 --single-branch --branch $Tag https://github.com/openai/codex.git $SourceDir
    if ($LASTEXITCODE -ne 0) { throw "openai/codex clone failed: $LASTEXITCODE" }

    $ProviderSource = Join-Path $SourceDir 'codex-rs\model-provider-info\src\lib.rs'
    $ProviderTests = Join-Path $SourceDir 'codex-rs\model-provider-info\src\model_provider_info_tests.rs'
    if (-not (Test-Path -LiteralPath $ProviderSource)) {
        throw "upstream provider source missing: $ProviderSource"
    }
    if (-not (Test-Path -LiteralPath $ProviderTests)) {
        throw "upstream provider test source missing: $ProviderTests"
    }
    $Text = [System.IO.File]::ReadAllText($ProviderSource)
    if ($Text.Contains($PatchMarker)) {
        throw 'fresh upstream source unexpectedly already contains the r94.1 private patch marker'
    }

    $CrLf = ([string][char]13) + [char]10
    $Lf = [string][char]10
    $Cr = [string][char]13
    $TextN = $Text.Replace($CrLf, $Lf).Replace($Cr, $Lf)
    $AnchorN = $MergeAnchor.Replace($CrLf, $Lf).Replace($Cr, $Lf)
    $ReplacementN = $MergeReplacement.Replace($CrLf, $Lf).Replace($Cr, $Lf)
    $First = $TextN.IndexOf($AnchorN, [System.StringComparison]::Ordinal)
    $Second = if ($First -ge 0) {
        $TextN.IndexOf($AnchorN, $First + $AnchorN.Length, [System.StringComparison]::Ordinal)
    } else { -1 }
    if ($First -lt 0 -or $Second -ge 0) {
        throw "upstream $Tag provider merge anchor must occur exactly once"
    }

    $TextN = $TextN.Replace($AnchorN, $ReplacementN)
    [System.IO.File]::WriteAllText(
        $ProviderSource,
        $TextN,
        [System.Text.UTF8Encoding]::new($false)
    )

    $Patched = [System.IO.File]::ReadAllText($ProviderSource)
    foreach ($Marker in @(
        $PatchMarker,
        'built_in_provider.stream_max_retries = provider.stream_max_retries',
        'built_in_provider.request_max_retries = provider.request_max_retries'
    )) {
        if (-not $Patched.Contains($Marker)) {
            throw "patched upstream source missing: $Marker"
        }
    }

    $TestText = [System.IO.File]::ReadAllText($ProviderTests)
    if ($TestText.Contains($PatchTestMarker)) {
        throw 'fresh upstream provider tests unexpectedly already contain the r94.1 private test marker'
    }
    [System.IO.File]::AppendAllText(
        $ProviderTests,
        $PatchTest.Replace($CrLf, $Lf).Replace($Cr, $Lf),
        [System.Text.UTF8Encoding]::new($false)
    )

    New-Item -ItemType Directory -Force -Path $BuildTarget | Out-Null
    $OldTarget = $env:CARGO_TARGET_DIR
    try {
        $env:CARGO_TARGET_DIR = $BuildTarget
        Push-Location (Join-Path $SourceDir 'codex-rs')
        try {
            cargo test -p codex-model-provider-info r94_1_builtin_openai_policy_overlay_reuses_retry_without_identity_change -- --test-threads=1
            if ($LASTEXITCODE -ne 0) {
                throw "r94.1 patched provider merge test failed: $LASTEXITCODE"
            }
            Write-Host 'R94_1_CODEX_RUNTIME_PROVIDER_MERGE_TEST_PASS' -ForegroundColor Green

            cargo build -p codex-cli --bin codex --release
            if ($LASTEXITCODE -ne 0) {
                throw "patched codex-cli build failed: $LASTEXITCODE"
            }
        }
        finally {
            Pop-Location
        }
    }
    finally {
        if ($null -eq $OldTarget) {
            Remove-Item Env:CARGO_TARGET_DIR -ErrorAction SilentlyContinue
        } else {
            $env:CARGO_TARGET_DIR = $OldTarget
        }
    }

    $BuiltExe = Join-Path $BuildTarget 'release\codex.exe'
    if (-not (Test-Path -LiteralPath $BuiltExe)) {
        throw "patched codex runtime not produced: $BuiltExe"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputPath) | Out-Null
    Copy-Item -LiteralPath $BuiltExe -Destination $OutputPath -Force

    $SourceCommit = (git -C $SourceDir rev-parse HEAD).Trim()
    [ordered]@{
        schemaVersion = 1
        patchRevision = $PatchRevision
        codexCliVersion = $CodexCliVersion
        upstreamTag = $Tag
        upstreamCommit = $SourceCommit
        bundledRuntime = $BundledRuntime
        builtAt = (Get-Date).ToString('o')
    } | ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath $MetadataPath -Encoding utf8NoBOM
}

$FinalVersion = (& $OutputPath --version 2>$null | Out-String).Trim()
$FinalVersionPattern = [regex]::Escape($CodexCliVersion)
if ($FinalVersion -notmatch "(?i)^codex-cli\s+$FinalVersionPattern(?:\s|$)") {
    throw "patched runtime version mismatch: expected=$CodexCliVersion actual=$FinalVersion"
}

Write-Host 'R94_1_CODEX_RUNTIME_BUILD_PASS' -ForegroundColor Green
Write-Host "  - bundled runtime: $BundledRuntime"
Write-Host "  - upstream tag: $Tag"
Write-Host "  - patched runtime: $OutputPath"
Write-Host '  - provider identity remains built-in openai; only portable policy fields are merged'
Write-Host '  - focused upstream merge test proved retry/timeouts change while built-in endpoint/name remain authoritative'
