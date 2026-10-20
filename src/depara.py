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


def identificar_novos_colaboradores(
    df_resultado: pd.DataFrame,
    indice_depara: "IndiceDePara",
) -> pd.DataFrame:
    """Identifica aprovadores encontrados via fallback de RH (Tier 1
    do `resolver.py`) que ainda não estão cadastrados na base de-para.

    São candidatos que a automação já sabe resolver hoje (por nome, no
    RH completo), mas que precisam ser incluídos no de-para para que,
    nas próximas rodadas, a resolução passe a ser feita direto pelo
    ID SAP (Tier 0, exata) -- sem depender de fallback.

    Retorna um DataFrame com uma linha por colaborador novo (dedup por
    ID SAP), pronto para ser usado em `montar_linhas_novos_colaboradores`.
    Não modifica `df_resultado` nem o de-para original."""

    linhas = df_resultado[
        (df_resultado["status"] == "APROVADOR_ENCONTRADO")
        & df_resultado["metodo_match"].fillna("").str.startswith("RH_FALLBACK_")
    ]

    vistos: set = set()
    registros = []
    for _, linha in linhas.iterrows():
        sap_id = linha["aprovador_sap_id"]
        if valor_vazio(sap_id):
            continue
        chave = normalizar_sap_id(sap_id)
        if not chave or chave in vistos or indice_depara.buscar_por_sap_id(chave) is not None:
            continue
        vistos.add(chave)
        registros.append(linha)

    return pd.DataFrame(registros) if registros else pd.DataFrame(columns=df_resultado.columns)


def montar_linhas_novos_colaboradores(
    df_novos: pd.DataFrame,
    mapeamento_depara: MapeamentoDePara,
) -> pd.DataFrame:
    """Converte o resultado de `identificar_novos_colaboradores` para o
    formato de colunas da base de-para, pronto para ser anexado a ela
    (ou exportado separadamente para revisão manual antes de subir ao
    SharePoint)."""

    m = mapeamento_depara
    registros = []
    for _, linha in df_novos.iterrows():
        registro = {m.coluna_sap_id: linha["aprovador_sap_id"], m.coluna_cargo: linha["aprovador_cargo"]}
        if m.coluna_nome_sap:
            registro[m.coluna_nome_sap] = linha["nome_sap_original"]
        if m.coluna_nome_rh:
            registro[m.coluna_nome_rh] = linha["aprovador_nome"]
        if m.coluna_gestor:
            registro[m.coluna_gestor] = linha["aprovador_gestor"]
        if m.coluna_email:
            registro[m.coluna_email] = linha["aprovador_email"]
        registros.append(registro)

    return pd.DataFrame(registros)


def adicionar_novos_colaboradores_ao_depara(
    df_depara: pd.DataFrame,
    df_novos: pd.DataFrame,
    mapeamento_depara: MapeamentoDePara,
    logger: logging.Logger,
) -> pd.DataFrame:
    """Retorna uma cópia do de-para (in memory) com os colaboradores
    novos anexados ao final. Colunas do de-para original que não têm
    equivalente no registro novo (ex.: CPF) ficam em branco -- a
    inclusão é "melhor esforço", para revisão humana antes de subir a
    planilha ao SharePoint."""

    if df_novos.empty:
        return df_depara

    linhas_novas = montar_linhas_novos_colaboradores(df_novos, mapeamento_depara)
    df_atualizado = pd.concat([df_depara, linhas_novas], ignore_index=True)

    logger.info(
        "%s colaborador(es) novo(s) (achado(s) via fallback de RH, ainda "
        "não cadastrado(s) no de-para) incluído(s) para revisão.",
        f"{len(linhas_novas):,}",
    )

    return df_atualizado
