$R86ObserverBodyPath = Join-Path $PSScriptRoot 'r86-timestamp-observer.js'
if (-not (Test-Path -LiteralPath $R86ObserverBodyPath)) { throw "r86 observer source missing: $R86ObserverBodyPath" }
$R86ObserverBody = [System.IO.File]::ReadAllText($R86ObserverBodyPath)
$R86ObserverWrapped = '$NewObserver = @''' + "`r`n" + $R86ObserverBody + "`r`n'@"
$R86ObserverReplacement = $R86ObserverWrapped + "`r`n`r`ntry {`r`n"
$PatchedR75 = Replace-BlockRequired $PatchedR75 '$NewObserver = @''' '    # Build r75 from the already-reviewed r74 local builder without copying its' $R86ObserverReplacement 'r86 live-only timestamp observer'
$PatchedR75 = $PatchedR75.Replace('try { sweepOutputSegments(true); } catch {}','try { sweepOutputSegments(false); } catch {}')
