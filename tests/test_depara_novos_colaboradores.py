import logging

import pandas as pd

from src.column_mapping import MapeamentoDePara
from src.depara import (
    IndiceDePara,
    adicionar_novos_colaboradores_ao_depara,
    identificar_novos_colaboradores,
)


MAPEAMENTO_DEPARA = MapeamentoDePara(
    coluna_sap_id="ID SAP",
    coluna_nome_sap="Nome SAP",
    coluna_nome_rh="Nome RH",
    coluna_cargo="Cargo",
    coluna_gestor="Gestor",
    coluna_email="E-mail",
    coluna_cpf=None,
)


def _df_depara_vazio() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ID SAP": ["123"],
            "Nome SAP": ["Maria Souza"],
            "Nome RH": ["Maria Souza"],
            "Cargo": ["Diretor"],
            "Gestor": ["Ana Lima"],
            "E-mail": ["maria@empresa.com"],
        }
    )


def _resultado_linha(sap_id, metodo_match, status="APROVADOR_ENCONTRADO"):
    return {
        "centro_custo": "CC1",
        "status": status,
        "aprovador_nome": "Joao Silva",
        "aprovador_cargo": "Diretor",
        "aprovador_gestor": "Carlos Mendes",
        "aprovador_email": "joao@empresa.com",
        "aprovador_sap_id": sap_id,
        "nome_sap_original": "Joao Silva",
        "metodo_match": metodo_match,
    }


def test_identifica_colaborador_novo_achado_via_fallback_rh():
    df_depara = _df_depara_vazio()
    indice = IndiceDePara(df_depara, MAPEAMENTO_DEPARA)
    df_resultado = pd.DataFrame([_resultado_linha("999", "RH_FALLBACK_NOME_EXATO")])

    novos = identificar_novos_colaboradores(df_resultado, indice)

    assert len(novos) == 1
    assert novos.iloc[0]["aprovador_sap_id"] == "999"


def test_ignora_colaborador_ja_cadastrado_no_depara():
    df_depara = _df_depara_vazio()
    indice = IndiceDePara(df_depara, MAPEAMENTO_DEPARA)
    df_resultado = pd.DataFrame([_resultado_linha("123", "RH_FALLBACK_NOME_EXATO")])

    novos = identificar_novos_colaboradores(df_resultado, indice)

    assert novos.empty


def test_ignora_resolucao_via_de_para_tier_0():
    df_depara = _df_depara_vazio()
    indice = IndiceDePara(df_depara, MAPEAMENTO_DEPARA)
    df_resultado = pd.DataFrame([_resultado_linha("999", "DE_PARA_SAP_ID_EXATO")])

    novos = identificar_novos_colaboradores(df_resultado, indice)

    assert novos.empty


def test_adicionar_novos_colaboradores_anexa_sem_alterar_linhas_existentes():
    df_depara = _df_depara_vazio()
    df_novos = pd.DataFrame([_resultado_linha("999", "RH_FALLBACK_NOME_EXATO")])

    df_atualizado = adicionar_novos_colaboradores_ao_depara(
        df_depara, df_novos, MAPEAMENTO_DEPARA, logging.getLogger("test")
    )

    assert len(df_atualizado) == 2
    assert df_atualizado.iloc[0]["ID SAP"] == "123"
    nova_linha = df_atualizado.iloc[1]
    assert nova_linha["ID SAP"] == "999"
    assert nova_linha["Cargo"] == "Diretor"
    assert nova_linha["Gestor"] == "Carlos Mendes"
