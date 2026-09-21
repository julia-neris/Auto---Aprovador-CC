"""
Reconciliação com a planilha da Belvitur.

Este é o passo final da automação: todo o trabalho de resolução de
aprovadores (`processor.processar_base_sap`) existe para alimentar
esta etapa, que é o que efetivamente é entregue para a Belvitur.

A planilha que a Belvitur envia (a última versão que eles têm) é
atualizada com duas novas colunas:

    APROVADOR SAP
        Nome do aprovador calculado para aquele Centro de Custo, ou o
        literal `config.TEXTO_INATIVAR_APROVADOR` ("INATIVAR") quando
        nenhum aprovador elegível foi encontrado.

    AÇÃO
        - vazia (`config.Acao.SEM_ACAO`): aprovador calculado é o
          mesmo que já está na planilha da Belvitur -- nada a fazer;
        - `config.Acao.ATUALIZAR`: aprovador calculado é diferente do
          que está cadastrado -- pede atualização;
        - `config.Acao.INATIVAR`: nenhum aprovador elegível foi
          encontrado -- pede inativação do Centro de Custo.

Além da planilha principal (todas as linhas, na ordem original da
Belvitur), é gerada a aba "ATUALIZAR": um subconjunto apenas com as
linhas que exigem alguma ação, já que só essas precisam de revisão
humana antes do envio.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import pandas as pd

from .column_mapping import MapeamentoBelvitur
from .config import Acao, TEXTO_INATIVAR_APROVADOR
from .normalization import normalizar_nome, valor_vazio
from .processor import STATUS_APROVADOR_ENCONTRADO


COLUNA_APROVADOR_SAP = "APROVADOR SAP"
COLUNA_ACAO = "AÇÃO"
COLUNA_APROVADOR_DO_APROVADOR = "APROVADOR DO APROVADOR"


def _mapa_resultado_por_centro_custo(df_resultado: pd.DataFrame) -> Dict[str, pd.Series]:
    """Indexa o resultado do `processor` por Centro de Custo (chave
    normalizada como texto), para join O(1) com a planilha da
    Belvitur -- evita merges custosos e explícita o que acontece
    quando a chave não bate (fica de fora do dicionário)."""

    mapa: Dict[str, pd.Series] = {}
    for _, linha in df_resultado.iterrows():
        chave = _normalizar_chave_centro_custo(linha["centro_custo"])
        if chave and chave not in mapa:
            mapa[chave] = linha
    return mapa


def _normalizar_chave_centro_custo(valor) -> str:
    if valor_vazio(valor):
        return ""
    # Centros de custo são numéricos/alfanuméricos; normaliza como
    # texto e remove zeros à esquerda apenas para strings puramente
    # numéricas, já que exportações diferentes (SAP vs. Belvitur)
    # podem gerar o mesmo código com ou sem zeros à esquerda ou como
    # float (ex.: 123.0 vs. "123").
    texto = str(valor).strip()
    if texto.endswith(".0"):
        texto = texto[:-2]
    texto = texto.lstrip("0") or "0"
    return texto.upper()


def reconciliar_com_belvitur(
    df_belvitur: pd.DataFrame,
    mapeamento_belvitur: MapeamentoBelvitur,
    df_resultado: pd.DataFrame,
    logger: logging.Logger,
) -> pd.DataFrame:
    """Retorna uma cópia de `df_belvitur` com as colunas
    `APROVADOR SAP` e `AÇÃO` adicionadas (ver regras no docstring do
    módulo). Não modifica `df_belvitur` original."""

    mapa_resultado = _mapa_resultado_por_centro_custo(df_resultado)

    df_saida = df_belvitur.copy()
    aprovadores_sap: list[str] = []
    acoes: list[str] = []
    aprovadores_do_aprovador: list[Optional[str]] = []
    centros_sem_resultado = 0

    # Comparação linha a linha por posição (`iloc`), já que o
    # `merge`/join do pandas exigiria uma coluna-chave auxiliar apenas
    # para isso e este acesso direto é igualmente claro e mais rápido
    # para as ~180 mil linhas da planilha da Belvitur.
    for posicao in range(len(df_saida)):
        valor_cc = df_saida.iloc[posicao][mapeamento_belvitur.coluna_centro_custo]
        aprovador_atual = df_saida.iloc[posicao][mapeamento_belvitur.coluna_aprovador_atual]
        chave = _normalizar_chave_centro_custo(valor_cc)
        linha_resultado = mapa_resultado.get(chave)

        if linha_resultado is None:
            centros_sem_resultado += 1
            aprovadores_sap.append("")
            acoes.append("")
            aprovadores_do_aprovador.append(None)
            continue

        if linha_resultado["status"] == STATUS_APROVADOR_ENCONTRADO:
            novo_aprovador = linha_resultado["aprovador_nome"]
            aprovadores_sap.append(novo_aprovador)

            if normalizar_nome(novo_aprovador) == normalizar_nome(aprovador_atual):
                acoes.append(Acao.SEM_ACAO)
                aprovadores_do_aprovador.append(None)
            else:
                acoes.append(Acao.ATUALIZAR)
                aprovadores_do_aprovador.append(linha_resultado.get("aprovador_gestor"))
        else:
            aprovadores_sap.append(TEXTO_INATIVAR_APROVADOR)
            if valor_vazio(aprovador_atual):
                # Já não havia aprovador cadastrado -- nada muda.
                acoes.append(Acao.SEM_ACAO)
            else:
                acoes.append(Acao.INATIVAR)
            aprovadores_do_aprovador.append(None)

    df_saida[COLUNA_APROVADOR_SAP] = aprovadores_sap
    df_saida[COLUNA_ACAO] = acoes
    df_saida[COLUNA_APROVADOR_DO_APROVADOR] = aprovadores_do_aprovador

    if centros_sem_resultado:
        logger.warning(
            "%s linha(s) da planilha da Belvitur têm Centro de Custo não "
            "encontrado na base SAP processada -- ficaram sem "
            "'%s'/'%s' preenchidos e devem ser revisadas manualmente.",
            f"{centros_sem_resultado:,}",
            COLUNA_APROVADOR_SAP,
            COLUNA_ACAO,
        )

    total_atualizar = (df_saida[COLUNA_ACAO] == Acao.ATUALIZAR).sum()
    total_inativar = (df_saida[COLUNA_ACAO] == Acao.INATIVAR).sum()
    logger.info(
        "Reconciliação com a Belvitur: %s linha(s) para ATUALIZAR, %s "
        "linha(s) para INATIVAR, %s sem ação necessária.",
        f"{total_atualizar:,}",
        f"{total_inativar:,}",
        f"{(len(df_saida) - total_atualizar - total_inativar):,}",
    )

    return df_saida


def gerar_excel_belvitur(df_saida: pd.DataFrame, caminho_saida: str) -> None:
    """Gera o Excel final para a Belvitur: aba principal com todas as
    linhas (mesma ordem/colunas originais + as três colunas novas) e
    aba "ATUALIZAR" apenas com as linhas que exigem ação."""

    df_atualizar = df_saida[df_saida[COLUNA_ACAO] != Acao.SEM_ACAO].copy()

    with pd.ExcelWriter(caminho_saida, engine="openpyxl") as writer:
        df_saida.to_excel(writer, sheet_name="Base Atualizada", index=False)
        df_atualizar.to_excel(writer, sheet_name="ATUALIZAR", index=False)
