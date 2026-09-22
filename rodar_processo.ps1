<#
    Script de atalho para rodar a automação de aprovadores.

    Como usar:
      1. Ajuste os caminhos na seção "CONFIGURE AQUI" abaixo, apontando
         para os arquivos do dia (SAP, de-para, RH e Belvitur).
      2. Rode este script com:
             .\rodar_processo.ps1
         (se o PowerShell bloquear a execução de scripts, rode antes,
         uma única vez, como administrador:
             Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
         )
      3. Ao final, os Excels gerados estarão na pasta "dados_saida".
#>

# ============================================================
# CONFIGURE AQUI -- ajuste os caminhos antes de rodar
# ============================================================

# Planilha extraída do SAP (Centro de Custo + candidatos N1..N6).
$Sap = "C:\Users\julia.neris\Downloads\teste - aprovadores 22.09\base sap.xlsx"

# Planilha "de-para" do SharePoint (ID SAP -> Cargo/Gestor).
$Depara = "C:\Users\julia.neris\Downloads\teste - aprovadores 22.09\de para CC - Aprovadores - 21;09.xlsx"

# Base de RH completa. É usada como fallback quando o ID SAP não está
# cadastrado no de-para.
$Rh = "C:\Users\julia.neris\Downloads\teste - aprovadores 22.09\BASE ATIVOS_DP 21.09 - RH.xlsx"

# Planilha enviada pela Belvitur neste ciclo. Troque este caminho a cada rodada.
$Belvitur = "C:\Users\julia.neris\Downloads\teste - aprovadores 22.09\base que devolvemos para a belvitur - Copia.xlsx"

# Se quiser atualizar Cargo/Gestor do de-para a partir do RH (via CPF)
# antes de processar, deixe $true. Requer $Rh preenchido.
$AtualizarDePara = $null

# Nomes dos Excels de saída (a pasta "dados_saida" é criada se não existir).
$SaidaAuditoria = "dados_saida\auditoria.xlsx"
$SaidaBelvitur  = "dados_saida\belvitur_atualizada.xlsx"

# ============================================================
# NÃO PRECISA MEXER DAQUI PARA BAIXO
# ============================================================

Set-Location $PSScriptRoot

New-Item -ItemType Directory -Force -Path "dados_saida" | Out-Null

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

# Evita mojibake no console ao exibir logs com acentuação.
chcp 65001 | Out-Null
$env:PYTHONIOENCODING = "utf-8"

$argumentos = @("-m", "src.main", "--sap", $Sap, "--depara", $Depara, "--saida", $SaidaAuditoria)

if ($Rh) {
    $argumentos += @("--rh", $Rh)
}

if ($AtualizarDePara) {
    if (-not $Rh) {
        Write-Warning "AtualizarDePara está ligado, mas `$Rh` não foi preenchido. Ignorando --atualizar-depara."
    } else {
        $argumentos += "--atualizar-depara"
    }
}

if ($Belvitur) {
    $argumentos += @("--belvitur", $Belvitur, "--saida-belvitur", $SaidaBelvitur)
}

Write-Host "Rodando: $Python $($argumentos -join ' ')" -ForegroundColor Cyan
& $Python @argumentos
$codigoSaida = $LASTEXITCODE

if ($codigoSaida -eq 0) {
    Write-Host ""
    Write-Host "Concluído com sucesso." -ForegroundColor Green
    Write-Host "Excel de auditoria: $SaidaAuditoria"
    if ($Belvitur) {
        Write-Host "Excel para a Belvitur: $SaidaBelvitur"
    }
} else {
    Write-Host ""
    Write-Host "O processo terminou com erro (código $codigoSaida). Veja a mensagem acima." -ForegroundColor Red
}

exit $codigoSaida
