"""
Geração do Excel de saída.

Produz um arquivo com quatro abas:
    - Aprovadores_Finais: um registro por Centro de Custo, já com todos
      os campos de auditoria (nível de origem, método, score,
      confiança, status, motivo).
    - Revisao_Manual: apenas os casos que não puderam ser decididos
      automaticamente (todo Status != APROVADOR_ENCONTRADO).
    - Resumo: indicadores agregados do processamento.
    - Trilha_Auditoria: todos os candidatos avaliados, linha a linha,
      incluindo os que foram pulados e o porquê.
"""

from __future__ import annotations

import os

import pandas as pd

from .processor import STATUS_APROVADOR_ENCONTRADO


_COLUNAS_RESULTADO_FINAL = {
    "centro_custo": "Centro de Custo",
    "descricao_centro_custo": "Descrição Centro de Custo",
    "aprovador_nome": "Aprovador Encontrado",
    "aprovador_cargo": "Cargo",
    "aprovador_sap_id": "ID SAP do Aprovador",
    "aprovador_gestor": "Gestor Direto do Aprovador",
    "aprovador_email": "E-mail do Aprovador",
    "nivel_sap_origem": "Nível SAP de Origem",
    "nome_sap_original": "Nome Original SAP",
    "nome_rh_encontrado": "Nome Encontrado (de-para/RH)",
    "metodo_match": "Método de Matching",
    "score_match": "Score",
    "confianca_match": "Confiança",
    "status": "Status",
    "motivo": "Motivo",
    "observacao": "Observação",
}

_COLUNAS_AUDITORIA = {
    "centro_custo": "Centro de Custo",
    "descricao_centro_custo": "Descrição Centro de Custo",
    "nivel_sap": "Nível SAP",
    "sap_id_buscado": "ID SAP Buscado",
    "nome_buscado_sap": "Nome Buscado (SAP)",
    "nome_encontrado": "Nome Encontrado (de-para/RH)",
    "cargo": "Cargo",
    "metodo": "Método",
    "score_final": "Score",
    "confianca": "Confiança",
    "elegivel": "Cargo Elegível?",
    "motivo": "Motivo",
    "selecionado": "Selecionado?",
}


def _renomear(df: pd.DataFrame, mapa: dict) -> pd.DataFrame:
    colunas_existentes = [c for c in mapa if c in df.columns]
    return df[colunas_existentes].rename(columns=mapa)


def _montar_resumo(df_resultado_bruto: pd.DataFrame, df_auditoria_bruto: pd.DataFrame) -> pd.DataFrame:
    total = len(df_resultado_bruto)
    contagem_status = df_resultado_bruto["status"].value_counts()
    contagem_confianca = (
        df_resultado_bruto.loc[
            df_resultado_bruto["status"] == STATUS_APROVADOR_ENCONTRADO, "confianca_match"
        ]
        .value_counts()
    )
    contagem_nivel = (
        df_resultado_bruto.loc[
            df_resultado_bruto["status"] == STATUS_APROVADOR_ENCONTRADO, "nivel_sap_origem"
        ]
        .value_counts()
    )
    contagem_cargo = (
        df_resultado_bruto.loc[
            df_resultado_bruto["status"] == STATUS_APROVADOR_ENCONTRADO, "aprovador_cargo"
        ]
        .value_counts()
    )

    linhas = [("Total de Centros de Custo processados", total)]

    linhas.append(("", ""))
    linhas.append(("-- Por status --", ""))
    for status, qtd in contagem_status.items():
        linhas.append((status, qtd))

    linhas.append(("", ""))
    linhas.append(("-- Confiança dos matches aceitos --", ""))
    for confianca, qtd in contagem_confianca.items():
        linhas.append((confianca, qtd))

    linhas.append(("", ""))
    linhas.append(("-- Aprovadores por nível SAP de origem --", ""))
    for nivel, qtd in contagem_nivel.items():
        linhas.append((nivel, qtd))

    linhas.append(("", ""))
    linhas.append(("-- Aprovadores por cargo --", ""))
    for cargo, qtd in contagem_cargo.items():
        linhas.append((cargo, qtd))

    return pd.DataFrame(linhas, columns=["Indicador", "Quantidade"])


def gerar_excel_saida(
    df_resultado_bruto: pd.DataFrame,
    df_auditoria_bruto: pd.DataFrame,
    caminho_saida: str,
) -> None:
    os.makedirs(os.path.dirname(caminho_saida) or ".", exist_ok=True)

    df_resultado = _renomear(df_resultado_bruto, _COLUNAS_RESULTADO_FINAL)
    df_auditoria = _renomear(df_auditoria_bruto, _COLUNAS_AUDITORIA)

    df_revisao = df_resultado[
        df_resultado["Status"] != STATUS_APROVADOR_ENCONTRADO
    ]

    df_resumo = _montar_resumo(df_resultado_bruto, df_auditoria_bruto)

    # Usamos o engine `xlsxwriter` em vez de `openpyxl` para escrita:
    # com a Trilha_Auditoria podendo ter centenas de milhares de
    # linhas (um evento por candidato avaliado, não só por Centro de
    # Custo), o `openpyxl` chega a levar minutos para gravar o
    # arquivo; o `xlsxwriter` é ordens de magnitude mais rápido para
    # esse tipo de escrita em lote.
    try:
        with pd.ExcelWriter(
            caminho_saida,
            engine="xlsxwriter",
            engine_kwargs={"options": {"strings_to_urls": False}},
        ) as writer:
            df_resultado.to_excel(writer, sheet_name="Aprovadores_Finais", index=False)
            df_revisao.to_excel(writer, sheet_name="Revisao_Manual", index=False)
            df_resumo.to_excel(writer, sheet_name="Resumo", index=False)
            df_auditoria.to_excel(writer, sheet_name="Trilha_Auditoria", index=False)

            for nome_aba, df_aba in (
                ("Aprovadores_Finais", df_resultado),
                ("Revisao_Manual", df_revisao),
                ("Resumo", df_resumo),
                ("Trilha_Auditoria", df_auditoria),
            ):
                _ajustar_largura_colunas(writer.sheets[nome_aba], df_aba)
    except PermissionError as exc:
        raise PermissionError(
            f"\nERRO: não foi possível salvar '{caminho_saida}'.\n"
            f"Provavelmente o arquivo está aberto no Excel. Feche-o e "
            f"execute novamente."
        ) from exc


def _ajustar_largura_colunas(worksheet, df: pd.DataFrame, largura_maxima: int = 60) -> None:
    # `set_column` é O(1) por coluna (não percorre linha a linha na
    # planilha), diferente de manipular `column_dimensions` célula a
    # célula -- importante para manter a geração do Excel rápida
    # mesmo com centenas de milhares de linhas.
    for indice_coluna, coluna in enumerate(df.columns):
        maior_valor = max(
            [len(str(coluna))] + [len(str(v)) for v in df[coluna].head(200)]
        )
        worksheet.set_column(indice_coluna, indice_coluna, min(maior_valor + 2, largura_maxima))
