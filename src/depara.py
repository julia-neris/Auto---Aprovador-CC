"""
Base "de-para" de aprovadores (SharePoint).

Diferente da base RH completa (25 mil funcionários), a base de-para é
um cadastro pequeno e curado (algumas centenas de linhas), mantido
manualmente pela área, que relaciona o ID SAP de cada possível
aprovador ao seu cargo/função e gestor direto ATUAIS.

Ela é a fonte PRIMÁRIA de cargo neste processo: como a chave é o ID
SAP (exato, sem ambiguidade de nome), a busca aqui é um simples
dicionário O(1) -- muito mais barato e muito mais confiável do que
qualquer matching por nome. O RH completo só entra em cena como
fallback, para os poucos IDs SAP usados na base SAP que não estão
cadastrados no de-para (ver `resolver.py`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd

from .column_mapping import MapeamentoDePara, MapeamentoRH
from .normalization import valor_vazio


def normalizar_sap_id(valor) -> str:
    """Normaliza um ID SAP para comparação (maiúsculo, sem espaços
    nas pontas). IDs SAP não têm acento/pontuação relevante, então uma
    normalização leve (sem a remoção agressiva feita para nomes) é
    suficiente e preserva dígitos/letras exatamente como estão."""

    if valor_vazio(valor):
        return ""
    return str(valor).strip().upper()


@dataclass
class InfoDePara:
    sap_id: str
    nome_sap: Optional[str]
    nome_rh: Optional[str]
    cargo: Optional[str]
    gestor: Optional[str]
    email: Optional[str]


class IndiceDePara:
    """Índice exato (dicionário) da base de-para, por ID SAP."""

    def __init__(self, df: pd.DataFrame, mapeamento: MapeamentoDePara):
        self.df = df.reset_index(drop=True)
        self.mapeamento = mapeamento

        self._indice: Dict[str, int] = {}
        ids_duplicados = 0

        for i, valor in enumerate(self.df[mapeamento.coluna_sap_id]):
            sap_id = normalizar_sap_id(valor)
            if not sap_id:
                continue
            if sap_id in self._indice:
                ids_duplicados += 1
                # Mantém a primeira ocorrência; duplicados são um
                # problema de qualidade de dados que já é reportado
                # por `validators.validar_base_depara`.
                continue
            self._indice[sap_id] = i

        self._ids_duplicados = ids_duplicados

    def __len__(self) -> int:
        return len(self._indice)

    def buscar_por_sap_id(self, sap_id) -> Optional[InfoDePara]:
        chave = normalizar_sap_id(sap_id)
        if not chave or chave not in self._indice:
            return None

        linha = self.df.iloc[self._indice[chave]]
        m = self.mapeamento

        return InfoDePara(
            sap_id=chave,
            nome_sap=linha[m.coluna_nome_sap] if m.coluna_nome_sap else None,
            nome_rh=linha[m.coluna_nome_rh] if m.coluna_nome_rh else None,
            cargo=linha[m.coluna_cargo],
            gestor=linha[m.coluna_gestor] if m.coluna_gestor else None,
            email=linha[m.coluna_email] if m.coluna_email else None,
        )


def atualizar_depara_com_rh(
    df_depara: pd.DataFrame,
    mapeamento_depara: MapeamentoDePara,
    df_rh: pd.DataFrame,
    mapeamento_rh: MapeamentoRH,
    logger: logging.Logger,
) -> pd.DataFrame:
    """Atualiza (in place, em uma cópia) as colunas de Cargo e Gestor
    da base de-para a partir da base RH completa, usando o CPF como
    chave de correspondência (mais confiável que nome para esse fim).

    Linhas do de-para sem CPF, ou cujo CPF não aparece no RH (ex.:
    pessoa desligada, contratação muito recente), são mantidas como
    estavam -- a atualização é "melhor esforço", nunca remove dados
    existentes. O chamador pode optar por pular esta etapa
    inteiramente quando não fizer sentido (ver `main.py`,
    `--atualizar-depara`)."""

    if not mapeamento_depara.coluna_cpf or not mapeamento_rh.coluna_cpf:
        logger.warning(
            "Atualização do de-para via RH ignorada: coluna de CPF não "
            "identificada em uma das duas bases."
        )
        return df_depara

    df_depara = df_depara.copy()

    def _cpf_normalizado(valor) -> str:
        if valor_vazio(valor):
            return ""
        return "".join(ch for ch in str(valor) if ch.isalnum()).upper()

    indice_rh_por_cpf: Dict[str, int] = {}
    for i, valor in enumerate(df_rh[mapeamento_rh.coluna_cpf]):
        cpf = _cpf_normalizado(valor)
        if cpf and cpf not in indice_rh_por_cpf:
            indice_rh_por_cpf[cpf] = i

    atualizados = 0
    nao_encontrados = 0

    for idx, cpf_valor in df_depara[mapeamento_depara.coluna_cpf].items():
        cpf = _cpf_normalizado(cpf_valor)
        if not cpf:
            continue

        posicao_rh = indice_rh_por_cpf.get(cpf)
        if posicao_rh is None:
            nao_encontrados += 1
            continue

        linha_rh = df_rh.iloc[posicao_rh]
        df_depara.at[idx, mapeamento_depara.coluna_cargo] = linha_rh[mapeamento_rh.coluna_cargo]
        if mapeamento_depara.coluna_gestor and mapeamento_rh.coluna_chefia:
            df_depara.at[idx, mapeamento_depara.coluna_gestor] = linha_rh[mapeamento_rh.coluna_chefia]
        atualizados += 1

    logger.info(
        "De-para atualizado via RH (CPF): %s registro(s) atualizados, "
        "%s CPF(s) do de-para não encontrados no RH (mantidos como "
        "estavam).",
        f"{atualizados:,}",
        f"{nao_encontrados:,}",
    )

    return df_depara
