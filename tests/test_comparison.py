import pandas as pd

from src.column_mapping import MapeamentoBelvitur
from src.comparison import comparar_com_referencia


def _mapeamento():
    return MapeamentoBelvitur(
        coluna_centro_custo="codigoCentroCusto",
        coluna_descricao_centro_custo=None,
        coluna_aprovador_atual="Aprovador",
    )


def test_comparacao_ignora_acao_e_compara_aprovador():
    referencia = pd.DataFrame(
        {
            "codigoCentroCusto": ["001", "002"],
            "Aprovador": ["Maria Souza", None],
        }
    )
    resultado = pd.DataFrame(
        {
            "centro_custo": [1, 2],
            "status": ["APROVADOR_ENCONTRADO", "SEM_APROVADOR"],
            "aprovador_nome": ["MARIA SOUZA", None],
        }
    )

    comparacao = comparar_com_referencia(referencia, _mapeamento(), resultado)

    assert comparacao["Resultado Comparação"].tolist() == ["IGUAL", "IGUAL"]
    assert comparacao["Aprovador Automatizado"].tolist() == [
        "MARIA SOUZA",
        "INATIVAR",
    ]


def test_comparacao_marca_aprovador_diferente():
    referencia = pd.DataFrame(
        {"codigoCentroCusto": ["003"], "Aprovador": ["Joao Pereira"]}
    )
    resultado = pd.DataFrame(
        {
            "centro_custo": ["003"],
            "status": ["APROVADOR_ENCONTRADO"],
            "aprovador_nome": ["MARIA SOUZA"],
        }
    )

    comparacao = comparar_com_referencia(referencia, _mapeamento(), resultado)

    assert comparacao.loc[0, "Resultado Comparação"] == "DIFERENTE"
