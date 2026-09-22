"""
Automação de definição de aprovadores SAP -- ponto de entrada.

Fluxo completo (ver `README.md` para o passo a passo de negócio):

    1. Lê a base SAP (Centro de Custo + candidatos a aprovador N1..N3).
    2. Lê a base "de-para" (SharePoint): cadastro curado de ID SAP ->
       cargo/gestor, opcionalmente atualizado a partir do RH completo
       via CPF (`--atualizar-depara`).
    3. (Opcional) Lê o RH completo como fallback de matching por nome,
       apenas para IDs SAP "órfãos" que não estão no de-para.
    4. Resolve, para cada Centro de Custo, o primeiro candidato
       elegível (Diretor/VP/CEO) na ordem SAP, até o nível configurado
       (`config.MAX_NIVEL_PROCESSAMENTO`, padrão N3).
    5. Gera o Excel de auditoria completo (`output.py`).
    6. (Opcional) Lê a planilha da Belvitur e gera a versão atualizada
       com as colunas "APROVADOR SAP" e "AÇÃO" (`belvitur.py`).

Uso:
    python -m src.main --sap sap.xlsx --depara depara.xlsx --saida resultado.xlsx
    python -m src.main --sap sap.xlsx --depara depara.xlsx --rh rh.xlsx \\
        --atualizar-depara --belvitur belvitur_anterior.xlsx --saida-belvitur belvitur_nova.xlsx
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# Permite executar tanto como `python src/main.py` quanto como
# `python -m src.main`, sem duplicar código entre os dois modos.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src import belvitur, column_mapping, config, depara, logging_utils, output, processor, validators
    from src.matching import IndiceRH
    from src.resolver import ResolvedorAprovador
else:
    from . import belvitur, column_mapping, config, depara, logging_utils, output, processor, validators
    from . import comparison
    from .matching import IndiceRH
    from .resolver import ResolvedorAprovador

import pandas as pd


def _validar_arquivo_existe(caminho: str, obrigatorio: bool = True) -> bool:
    if os.path.isfile(caminho):
        return True
    if obrigatorio:
        raise FileNotFoundError(
            f"\nArquivo não encontrado:\n{caminho}\n\n"
            f"Verifique o caminho informado (use os argumentos de linha de "
            f"comando para apontar para outro arquivo -- veja `python -m "
            f"src.main --help`)."
        )
    return False


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Automação de definição de aprovadores SAP a partir das bases "
            "SAP, de-para e (opcionalmente) RH e Belvitur."
        )
    )
    parser.add_argument(
        "--sap", default=config.ARQUIVO_SAP_PADRAO, help="Caminho da planilha extraída do SAP."
    )
    parser.add_argument(
        "--depara",
        default=config.ARQUIVO_DEPARA_PADRAO,
        help="Caminho da planilha de-para (SAP ID -> cargo/gestor).",
    )
    parser.add_argument(
        "--rh",
        default=None,
        help=(
            "Caminho da planilha de RH completa (opcional). Usada como "
            "fallback de matching por nome apenas para IDs SAP não "
            "cadastrados no de-para, e para atualizar o de-para via "
            "--atualizar-depara."
        ),
    )
    parser.add_argument(
        "--atualizar-depara",
        action="store_true",
        help="Atualiza Cargo/Gestor do de-para a partir do RH completo (via CPF) antes de processar.",
    )
    parser.add_argument(
        "--saida",
        default=config.ARQUIVO_SAIDA_PADRAO,
        help="Caminho do Excel de auditoria a ser gerado.",
    )
    parser.add_argument(
        "--belvitur",
        default=None,
        help="Caminho da planilha da Belvitur (versão anterior) a ser atualizada (opcional).",
    )
    parser.add_argument(
        "--saida-belvitur",
        default=config.ARQUIVO_SAIDA_BELVITUR_PADRAO,
        help="Caminho do Excel atualizado para a Belvitur a ser gerado (requer --belvitur).",
    )
    parser.add_argument(
        "--sheet-sap", default=0, help="Nome ou índice da aba a usar na planilha SAP (padrão: primeira)."
    )
    parser.add_argument(
        "--sheet-depara", default=0, help="Nome ou índice da aba a usar na planilha de-para (padrão: primeira)."
    )
    parser.add_argument(
        "--sheet-rh", default=0, help="Nome ou índice da aba a usar na planilha RH (padrão: primeira)."
    )
    parser.add_argument(
        "--sheet-belvitur", default=0, help="Nome ou índice da aba a usar na planilha da Belvitur (padrão: primeira)."
    )
    parser.add_argument(
        "--referencia-manual",
        default=None,
        help="Planilha manual de referência para comparar aprovadores, sem considerar AÇÃO.",
    )
    parser.add_argument(
        "--saida-comparacao",
        default="dados_saida/comparacao_manual.xlsx",
        help="Caminho do relatório da comparação manual.",
    )
    return parser.parse_args(argv)


def executar(argv=None) -> int:
    args = _parse_args(argv)
    logger = logging_utils.configurar_logger()

    logger.info("=" * 80)
    logger.info("AUTOMAÇÃO DE APROVADORES SAP")
    logger.info("=" * 80)

    inicio = time.time()

    try:
        logger.info("Validando arquivos de entrada...")
        _validar_arquivo_existe(args.sap)
        _validar_arquivo_existe(args.depara)
        usar_rh = args.rh is not None and _validar_arquivo_existe(args.rh, obrigatorio=True)
        usar_belvitur = args.belvitur is not None
        if usar_belvitur:
            _validar_arquivo_existe(args.belvitur)
        usar_referencia_manual = args.referencia_manual is not None
        if usar_referencia_manual:
            _validar_arquivo_existe(args.referencia_manual)

        logger.info("Carregando base SAP: %s", args.sap)
        df_sap = pd.read_excel(args.sap, sheet_name=args.sheet_sap)
        df_sap = column_mapping.limpar_nomes_colunas(df_sap)

        logger.info("Carregando base de-para: %s", args.depara)
        df_depara = pd.read_excel(args.depara, sheet_name=args.sheet_depara)
        df_depara = column_mapping.limpar_nomes_colunas(df_depara)

        df_rh = None
        mapeamento_rh = None
        if usar_rh:
            logger.info("Carregando base RH: %s", args.rh)
            df_rh = pd.read_excel(args.rh, sheet_name=args.sheet_rh)
            df_rh = column_mapping.limpar_nomes_colunas(df_rh)
            mapeamento_rh = column_mapping.detectar_mapeamento_rh(df_rh)
            validators.validar_base_rh(df_rh, mapeamento_rh, logger)

        logger.info("Identificando colunas da base SAP...")
        mapeamento_sap = column_mapping.detectar_mapeamento_sap(df_sap)
        logger.info(
            "Centro de Custo: '%s' | Descrição: '%s' | Níveis de aprovador detectados: %s",
            mapeamento_sap.coluna_centro_custo,
            mapeamento_sap.coluna_descricao_centro_custo,
            ", ".join(f"{n.rotulo}:'{n.coluna_nome}'" for n in mapeamento_sap.niveis),
        )

        logger.info("Identificando colunas da base de-para...")
        mapeamento_depara = column_mapping.detectar_mapeamento_depara(df_depara)
        logger.info(
            "ID SAP: '%s' | Cargo: '%s' | Gestor: '%s' | CPF: '%s'",
            mapeamento_depara.coluna_sap_id,
            mapeamento_depara.coluna_cargo,
            mapeamento_depara.coluna_gestor,
            mapeamento_depara.coluna_cpf,
        )

        logger.info("Validando qualidade dos dados...")
        validators.validar_base_sap(df_sap, mapeamento_sap, logger)
        validators.validar_base_depara(df_depara, mapeamento_depara, logger)

        if args.atualizar_depara:
            if not usar_rh:
                logger.warning(
                    "--atualizar-depara foi solicitado, mas nenhuma base RH "
                    "(--rh) foi informada; a atualização será ignorada."
                )
            else:
                logger.info("Atualizando de-para a partir do RH completo (via CPF)...")
                df_depara = depara.atualizar_depara_com_rh(
                    df_depara, mapeamento_depara, df_rh, mapeamento_rh, logger
                )

        logger.info("Construindo índice do de-para (Tier 0)...")
        indice_depara = depara.IndiceDePara(df_depara, mapeamento_depara)

        indice_rh_fallback = None
        if usar_rh:
            logger.info("Construindo índice do RH completo (Tier 1, fallback)...")
            indice_rh_fallback = IndiceRH(df_rh, mapeamento_rh)
        else:
            logger.warning(
                "Nenhuma base RH informada -- candidatos com ID SAP não "
                "cadastrado no de-para serão reportados como não "
                "encontrados, sem tentativa de matching por nome."
            )

        resolvedor = ResolvedorAprovador(indice_depara, indice_rh_fallback)

        df_resultado, df_auditoria = processor.processar_base_sap(
            df_sap, mapeamento_sap, resolvedor, logger
        )

        total = len(df_resultado)
        sucesso = (df_resultado["status"] == processor.STATUS_APROVADOR_ENCONTRADO).sum()
        logger.info(
            "Processamento concluído: %s/%s Centros de Custo com aprovador definido (%.1f%%).",
            f"{sucesso:,}",
            f"{total:,}",
            (sucesso / total) * 100 if total else 0.0,
        )

        logger.info("Gerando Excel de auditoria: %s", args.saida)
        output.gerar_excel_saida(df_resultado, df_auditoria, args.saida)

        if usar_belvitur:
            logger.info("Carregando planilha da Belvitur: %s", args.belvitur)
            df_belvitur = pd.read_excel(args.belvitur, sheet_name=args.sheet_belvitur)
            df_belvitur = column_mapping.limpar_nomes_colunas(df_belvitur)

            mapeamento_belvitur = column_mapping.detectar_mapeamento_belvitur(df_belvitur)
            logger.info(
                "Centro de Custo: '%s' | Aprovador atual: '%s'",
                mapeamento_belvitur.coluna_centro_custo,
                mapeamento_belvitur.coluna_aprovador_atual,
            )
            validators.validar_base_belvitur(df_belvitur, mapeamento_belvitur, logger)

            df_belvitur_atualizada = belvitur.reconciliar_com_belvitur(
                df_belvitur, mapeamento_belvitur, df_resultado, logger
            )

            logger.info("Gerando Excel atualizado para a Belvitur: %s", args.saida_belvitur)
            belvitur.gerar_excel_belvitur(df_belvitur_atualizada, args.saida_belvitur)

        if usar_referencia_manual:
            logger.info("Carregando referência manual: %s", args.referencia_manual)
            df_referencia = pd.read_excel(
                args.referencia_manual, sheet_name=args.sheet_belvitur
            )
            df_referencia = column_mapping.limpar_nomes_colunas(df_referencia)
            mapeamento_referencia = column_mapping.detectar_mapeamento_belvitur(
                df_referencia
            )
            df_comparacao = comparison.comparar_com_referencia(
                df_referencia, mapeamento_referencia, df_resultado
            )
            logger.info("Gerando comparação manual: %s", args.saida_comparacao)
            comparison.gerar_excel_comparacao(df_comparacao, args.saida_comparacao)

        duracao = time.time() - inicio
        logger.info("Concluído em %.1f segundos.", duracao)

        return 0

    except (
        FileNotFoundError,
        column_mapping.ColunaNaoEncontradaError,
        validators.QualidadeDadosError,
        PermissionError,
    ) as exc:
        logger.error(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(executar())
