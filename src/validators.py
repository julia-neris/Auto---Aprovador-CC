"""
Validações de qualidade de dados.

Executadas antes do processamento pesado, para falhar rápido e com
mensagens claras quando os dados de entrada tiverem problemas
estruturais graves (planilha vazia, colunas essenciais totalmente
vazias, etc.). Problemas "leves" (duplicados, poucos vazios) são
apenas registrados no log, não interrompem a execução.
"""

from __future__ import annotations

import logging
from typing import List

import pandas as pd

from .column_mapping import MapeamentoBelvitur, MapeamentoDePara, MapeamentoRH, MapeamentoSAP
from .depara import normalizar_sap_id
from .normalization import normalizar_nome, valor_vazio


class QualidadeDadosError(Exception):
    """Levantada quando um problema estrutural grave impede a
    continuidade segura do processamento."""


def validar_base_sap(df: pd.DataFrame, mapeamento: MapeamentoSAP, logger: logging.Logger) -> None:
    if df.empty:
        raise QualidadeDadosError("A base SAP está vazia (0 linhas). Nada a processar.")

    total_linhas = len(df)
    logger.info("Base SAP: %s linhas, %s colunas.", f"{total_linhas:,}", len(df.columns))

    cc_vazio = df[mapeamento.coluna_centro_custo].apply(valor_vazio).sum()
    if cc_vazio:
        logger.warning(
            "%s linha(s) sem valor na coluna de Centro de Custo ('%s').",
            f"{cc_vazio:,}",
            mapeamento.coluna_centro_custo,
        )

    duplicados_cc = df[mapeamento.coluna_centro_custo].duplicated().sum()
    if duplicados_cc:
        logger.warning(
            "%s Centro(s) de Custo aparecem em mais de uma linha na base SAP.",
            f"{duplicados_cc:,}",
        )

    for nivel in mapeamento.niveis:
        vazios = df[nivel.coluna_nome].apply(valor_vazio).sum()
        proporcao = (vazios / total_linhas) * 100 if total_linhas else 0
        logger.info(
            "Nível %-4s (%s): %s vazios (%.1f%%).",
            nivel.rotulo,
            nivel.coluna_nome,
            f"{vazios:,}",
            proporcao,
        )

    todos_vazios = df[[n.coluna_nome for n in mapeamento.niveis]].apply(
        lambda linha: all(valor_vazio(v) for v in linha), axis=1
    )
    total_sem_nenhum_candidato = todos_vazios.sum()
    if total_sem_nenhum_candidato:
        logger.warning(
            "%s linha(s) sem NENHUM candidato a aprovador preenchido (todos os níveis vazios).",
            f"{total_sem_nenhum_candidato:,}",
        )


def validar_base_rh(df: pd.DataFrame, mapeamento: MapeamentoRH, logger: logging.Logger) -> None:
    if df.empty:
        raise QualidadeDadosError("A base RH está vazia (0 linhas). Nada para relacionar.")

    logger.info("Base RH: %s linhas, %s colunas.", f"{len(df):,}", len(df.columns))

    nomes_vazios = df[mapeamento.coluna_nome].apply(valor_vazio).sum()
    if nomes_vazios:
        logger.warning(
            "%s linha(s) da base RH sem nome preenchido -- serão ignoradas no índice.",
            f"{nomes_vazios:,}",
        )

    cargos_vazios = df[mapeamento.coluna_cargo].apply(valor_vazio).sum()
    if cargos_vazios:
        logger.warning(
            "%s pessoa(s) no RH sem cargo/função preenchido -- nunca serão elegíveis como aprovador.",
            f"{cargos_vazios:,}",
        )

    nomes_normalizados = df[mapeamento.coluna_nome].apply(normalizar_nome)
    nomes_normalizados = nomes_normalizados[nomes_normalizados != ""]
    duplicados = nomes_normalizados.duplicated(keep=False).sum()
    if duplicados:
        logger.warning(
            "%s registro(s) no RH compartilham o nome normalizado com outra pessoa "
            "(possível homônimo). Esses nomes não serão escolhidos automaticamente "
            "em caso de ambiguidade no match exato.",
            f"{duplicados:,}",
        )

    if mapeamento.coluna_cpf:
        cpf_duplicado = df[mapeamento.coluna_cpf].dropna().duplicated().sum()
        if cpf_duplicado:
            logger.warning(
                "%s CPF(s) duplicados na base RH -- verifique possíveis registros repetidos.",
                f"{cpf_duplicado:,}",
            )


def validar_base_depara(
    df: pd.DataFrame, mapeamento: MapeamentoDePara, logger: logging.Logger
) -> None:
    if df.empty:
        raise QualidadeDadosError(
            "A base de-para está vazia (0 linhas). Ela é a fonte primária de "
            "cargo/gestor por ID SAP -- sem ela, a resolução cai inteiramente "
            "no fallback por nome contra o RH completo, o que é mais lento e "
            "menos confiável."
        )

    logger.info("Base de-para: %s linhas, %s colunas.", f"{len(df):,}", len(df.columns))

    ids_vazios = df[mapeamento.coluna_sap_id].apply(valor_vazio).sum()
    if ids_vazios:
        logger.warning(
            "%s linha(s) do de-para sem ID SAP preenchido -- serão ignoradas no índice.",
            f"{ids_vazios:,}",
        )

    ids_normalizados = df[mapeamento.coluna_sap_id].apply(normalizar_sap_id)
    ids_normalizados = ids_normalizados[ids_normalizados != ""]
    ids_duplicados = ids_normalizados.duplicated().sum()
    if ids_duplicados:
        logger.warning(
            "%s ID(s) SAP duplicados na base de-para -- apenas a primeira "
            "ocorrência de cada ID é usada; revise a planilha para evitar "
            "cargo/gestor desatualizado ou inconsistente.",
            f"{ids_duplicados:,}",
        )

    cargos_vazios = df[mapeamento.coluna_cargo].apply(valor_vazio).sum()
    if cargos_vazios:
        logger.warning(
            "%s registro(s) do de-para sem cargo preenchido -- nunca serão "
            "elegíveis como aprovador enquanto isso não for corrigido.",
            f"{cargos_vazios:,}",
        )

    if mapeamento.coluna_cpf:
        cpf_vazio = df[mapeamento.coluna_cpf].apply(valor_vazio).sum()
        if cpf_vazio:
            logger.warning(
                "%s linha(s) do de-para sem CPF -- não poderão ser "
                "atualizadas automaticamente a partir do RH completo.",
                f"{cpf_vazio:,}",
            )


def validar_base_belvitur(
    df: pd.DataFrame, mapeamento: MapeamentoBelvitur, logger: logging.Logger
) -> None:
    if df.empty:
        raise QualidadeDadosError(
            "A planilha da Belvitur está vazia (0 linhas). Nada a reconciliar."
        )

    logger.info("Base Belvitur: %s linhas, %s colunas.", f"{len(df):,}", len(df.columns))

    cc_vazio = df[mapeamento.coluna_centro_custo].apply(valor_vazio).sum()
    if cc_vazio:
        logger.warning(
            "%s linha(s) da planilha da Belvitur sem Centro de Custo preenchido.",
            f"{cc_vazio:,}",
        )

    duplicados_cc = df[mapeamento.coluna_centro_custo].duplicated().sum()
    if duplicados_cc:
        logger.info(
            "%s linha(s) com Centro de Custo repetido na Belvitur (esperado: "
            "a planilha costuma ter uma linha por política de aprovação para "
            "o mesmo Centro de Custo).",
            f"{duplicados_cc:,}",
        )
