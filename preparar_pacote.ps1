$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$PackageRoot = Join-Path $ProjectRoot "dist\aprovadores-local"
$ZipPath = Join-Path $ProjectRoot "dist\aprovadores-local.zip"

$RequiredPaths = @(
    "src",
    "web",
    "requirements.txt",
    "abrir_aplicacao.ps1",
    "LEIA-ME-APLICACAO-LOCAL.txt"
)
foreach ($relativePath in $RequiredPaths) {
    if (-not (Test-Path (Join-Path $ProjectRoot $relativePath))) {
        throw "Falta o arquivo necessário para montar o pacote: $relativePath"
    }
}

if (Test-Path $PackageRoot) {
    Remove-Item -LiteralPath $PackageRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $PackageRoot | Out-Null
foreach ($relativePath in $RequiredPaths) {
    $source = Join-Path $ProjectRoot $relativePath
    $destination = Join-Path $PackageRoot $relativePath
    if (Test-Path -LiteralPath $source -PathType Container) {
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        Copy-Item -Path (Join-Path $source "*") -Destination $destination -Recurse -Force
    } else {
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
}

Get-ChildItem -LiteralPath $PackageRoot -Directory -Filter __pycache__ -Recurse | Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $PackageRoot -File -Recurse |
    Where-Object { $_.Extension -in ".pyc", ".pyo", ".xlsx", ".xlsm", ".xls" } |
    Remove-Item -Force

if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -Path (Join-Path $PackageRoot "*") -DestinationPath $ZipPath -CompressionLevel Optimal
Write-Host "Pacote local criado: $ZipPath" -ForegroundColor Green
Write-Host "Compartilhe-o somente pelo canal aprovado pela empresa." -ForegroundColor DarkGray
