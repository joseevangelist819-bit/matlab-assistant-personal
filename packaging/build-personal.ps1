param([string]$Version='1.1.0-personal')
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$publish=Join-Path $root 'dist'
New-Item -ItemType Directory -Force -Path $publish|Out-Null
$zip=Join-Path $publish "matlab-assistant-source-$Version.zip"
if(Test-Path $zip){Remove-Item -LiteralPath $zip -Force}
$items=@('workflow_engine','tests','examples','docs','packaging','pyproject.toml','README.md','.gitignore','RIGHTS.md')
$paths=$items|ForEach-Object{Join-Path $root $_}|Where-Object{Test-Path -LiteralPath $_}
Compress-Archive -LiteralPath $paths -DestinationPath $zip -CompressionLevel Optimal
$hash=(Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $([IO.Path]::GetFileName($zip))"|Set-Content -LiteralPath (Join-Path $publish 'SHA256.txt') -Encoding ASCII
Write-Output $zip
