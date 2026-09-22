import logging

import pandas as pd

from src.belvitur import (
    COLUNA_ACAO,
    COLUNA_APROVADOR_SAP,
    reconciliar_com_belvitur,
)
from src.column_mapping import MapeamentoBelvitur
from src.config import Acao


MAPEAMENTO = MapeamentoBelvitur(
    coluna_centro_custo="codigoCentroCusto",
    coluna_descricao_centro_custo=None,
    coluna_aprovador_atual="Aprovador",
)


def _resultado(centro, status, aprovador=None):
    return pd.DataFrame(
        {
            "centro_custo": [centro],
            "status": [status],
            "aprovador_nome": [aprovador],
            "aprovador_gestor": [None],
        }
    )


def test_aprovador_igual_marca_manter():
    entrada = pd.DataFrame({"codigoCentroCusto": ["CC1"], "Aprovador": ["Maria Souza"]})
    saida = reconciliar_com_belvitur(
        entrada,
        MAPEAMENTO,
        _resultado("CC1", "APROVADOR_ENCONTRADO", "MARIA SOUZA"),
        logging.getLogger("test"),
    )

    assert saida.loc[0, COLUNA_ACAO] == Acao.MANTER
    assert saida.loc[0, COLUNA_APROVADOR_SAP] == "MARIA SOUZA"


def test_sem_aprovador_marca_inativar_mesmo_se_ja_estiver_vazio():
    entrada = pd.DataFrame({"codigoCentroCusto": ["CC1"], "Aprovador": [None]})
    saida = reconciliar_com_belvitur(
        entrada,
        MAPEAMENTO,
        _resultado("CC1", "SEM_APROVADOR"),
        logging.getLogger("test"),
    )

    assert saida.loc[0, COLUNA_ACAO] == Acao.INATIVAR
    assert saida.loc[0, COLUNA_APROVADOR_SAP] == "INATIVAR"
