"""Comparação do resultado automatizado com uma referência manual."""

from __future__ import annotations

import os
from typing import Dict

import pandas as pd

from .belvitur import _normalizar_chave_centro_custo
from .column_mapping import MapeamentoBelvitur
from .config import TEXTO_INATIVAR_APROVADOR
from .normalization import normalizar_nome, valor_vazio
from .processor import STATUS_APROVADOR_ENCONTRADO

COLUNA_RESULTADO_COMPARACAO = "Resultado Comparação"
COLUNA_APROVADOR_AUTOMATIZADO = "Aprovador Automatizado"


def _mapa_resultado(df_resultado: pd.DataFrame) -> Dict[str, str]:
    mapa: Dict[str, str] = {}
    for _, linha in df_resultado.iterrows():
        chave = _normalizar_chave_centro_custo(linha["centro_custo"])
        if not chave or chave in mapa:
            continue
        if linha["status"] == STATUS_APROVADOR_ENCONTRADO:
            mapa[chave] = str(linha["aprovador_nome"])
        else:
            mapa[chave] = TEXTO_INATIVAR_APROVADOR
    return mapa


def _valor_referencia(valor) -> str:
    if valor_vazio(valor):
        return TEXTO_INATIVAR_APROVADOR
    return str(valor).strip()


def comparar_com_referencia(
    df_referencia: pd.DataFrame,
    mapeamento_referencia: MapeamentoBelvitur,
    df_resultado: pd.DataFrame,
) -> pd.DataFrame:
    """Compara o aprovador manual com o calculado, ignorando AÇÃO."""

    mapa_resultado = _mapa_resultado(df_resultado)
    saida = df_referencia.copy()
    aprovadores_automatizados: list[str] = []
    resultados: list[str] = []

    for _, linha in saida.iterrows():
        chave = _normalizar_chave_centro_custo(
            linha[mapeamento_referencia.coluna_centro_custo]
        )
        esperado = _valor_referencia(
            linha[mapeamento_referencia.coluna_aprovador_atual]
        )
        if chave not in mapa_resultado:
            aprovadores_automatizados.append("")
            resultados.append("CC_NAO_ENCONTRADO")
            continue

        calculado = mapa_resultado[chave]
        aprovadores_automatizados.append(calculado)
        resultados.append(
            "IGUAL"
            if normalizar_nome(esperado) == normalizar_nome(calculado)
            else "DIFERENTE"
        )

    saida[COLUNA_APROVADOR_AUTOMATIZADO] = aprovadores_automatizados
    saida[COLUNA_RESULTADO_COMPARACAO] = resultados
    return saida


def gerar_excel_comparacao(df_comparacao: pd.DataFrame, caminho_saida: str) -> None:
    """Grava a comparação detalhada e um resumo sem considerar AÇÃO."""

    os.makedirs(os.path.dirname(caminho_saida) or ".", exist_ok=True)
    contagem = df_comparacao[COLUNA_RESULTADO_COMPARACAO].value_counts()
    resumo = pd.DataFrame(
        [(resultado, quantidade) for resultado, quantidade in contagem.items()],
        columns=["Resultado", "Quantidade"],
    )

    with pd.ExcelWriter(caminho_saida, engine="xlsxwriter") as writer:
        df_comparacao.to_excel(writer, sheet_name="Comparacao", index=False)
        resumo.to_excel(writer, sheet_name="Resumo", index=False)
