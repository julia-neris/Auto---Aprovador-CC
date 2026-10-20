$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Requirements = Join-Path $ProjectRoot "requirements.txt"
$RequirementsStamp = Join-Path $ProjectRoot ".venv\requirements.sha256"

if (-not (Test-Path $Requirements)) {
    throw "Não encontrei requirements.txt. Extraia o pacote completo e execute este script na pasta raiz."
}

if (-not (Test-Path $VenvPython)) {
    $PythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($PythonLauncher) {
        & $PythonLauncher.Source -3 -m venv (Join-Path $ProjectRoot ".venv")
    } else {
        $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if (-not $PythonCommand) {
            throw "Python não encontrado. Peça à TI para disponibilizar Python 3 no seu perfil ou instalar as dependências aprovadas."
        }
        & $PythonCommand.Source -m venv (Join-Path $ProjectRoot ".venv")
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Não consegui preparar o ambiente Python local. Confirme com a TI se Python e venv estão disponíveis para sua conta."
    }
}

$RequirementsHash = (Get-FileHash -LiteralPath $Requirements -Algorithm SHA256).Hash
$InstalledHash = if (Test-Path $RequirementsStamp) {
    (Get-Content -LiteralPath $RequirementsStamp -Raw).Trim()
} else {
    ""
}

if ($RequirementsHash -ne $InstalledHash) {
    Write-Host "Preparando dependências para este usuário..." -ForegroundColor Cyan
    & $VenvPython -m pip install -r $Requirements
    if ($LASTEXITCODE -ne 0) {
        throw "A instalação das dependências falhou. Verifique o acesso ao repositório de pacotes permitido pela empresa ou peça apoio à TI."
    }
    Set-Content -LiteralPath $RequirementsStamp -Value $RequirementsHash -NoNewline -Encoding ascii
}

$Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$Listener.Start()
$Port = $Listener.LocalEndpoint.Port
$Listener.Stop()

$env:PORT = [string]$Port
$env:APROVADORES_OPEN_BROWSER = "1"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "Abrindo a automação neste computador: http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "Os arquivos selecionados ficam neste computador. Feche esta janela para encerrar o servidor." -ForegroundColor DarkGray
& $VenvPython -m web.app
exit $LASTEXITCODE
