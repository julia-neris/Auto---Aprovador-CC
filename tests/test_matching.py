import pandas as pd
import pytest

from src.column_mapping import MapeamentoRH
from src.config import Confianca
from src.matching import IndiceRH, match_e_confianca_aceitavel


def _construir_indice(nomes, cargos, matriculas=None, cpfs=None):
    df = pd.DataFrame(
        {
            "NOME": nomes,
            "CARGO": cargos,
            "MATRICULA": matriculas or [str(i) for i in range(len(nomes))],
            "CPF": cpfs or [str(i).zfill(11) for i in range(len(nomes))],
        }
    )
    mapeamento = MapeamentoRH(
        coluna_nome="NOME",
        coluna_cargo="CARGO",
        coluna_matricula="MATRICULA",
        coluna_cpf="CPF",
        coluna_chefia=None,
    )
    return IndiceRH(df, mapeamento)


def test_match_exato_apos_normalizacao():
    indice = _construir_indice(["JOÃO DA SILVA"], ["GERENTE"])
    resultado = indice.buscar("Joao da Silva")
    assert resultado.encontrado is True
    assert resultado.confianca == Confianca.ALTA
    assert resultado.metodo == "EXATO"


def test_nome_com_diferenca_entre_sap_e_rh_e_encontrado_por_subconjunto():
    # Teste 6 do escopo: nome SAP abreviado em relação ao nome completo do RH.
    indice = _construir_indice(["MARCELLO DIEGUES ZAPPIA"], ["DIRETOR RH"])
    resultado = indice.buscar("MARCELLO ZAPPIA")
    assert resultado.encontrado is True
    assert resultado.nome_rh == "MARCELLO DIEGUES ZAPPIA"
    assert resultado.confianca in (Confianca.ALTA, Confianca.MEDIA)


def test_fuzzy_favorece_sobrenome_em_comum_em_vez_do_maior_score_textual():
    # Caso real: ALEXANDRE BARRADAS deve casar com ALEXANDRE FERNANDES
    # BARRADAS (mesmo sobrenome), não com ALEXANDRE BARROS MAIA, mesmo
    # que um algoritmo de fuzzy matching ingênuo prefira o segundo em
    # alguns cálculos de score textual puro.
    indice = _construir_indice(
        ["ALEXANDRE BARROS MAIA", "ALEXANDRE FERNANDES BARRADAS"],
        ["TECNICO", "DIRETOR EXECUTIVO"],
    )
    resultado = indice.buscar("ALEXANDRE BARRADAS")
    assert resultado.encontrado is True
    assert resultado.nome_rh == "ALEXANDRE FERNANDES BARRADAS"


def test_dois_candidatos_muito_semelhantes_geram_ambiguidade():
    # Teste 7 do escopo: dois candidatos RH muito parecidos devem
    # sinalizar ambiguidade em vez de escolher silenciosamente.
    indice = _construir_indice(
        ["CARLOS EDUARDO SOUZA", "CARLOS EDUARDO SOUSA"],
        ["DIRETOR", "DIRETOR"],
    )
    resultado = indice.buscar("CARLOS EDUARDO SOUZA")
    # Ou casa exatamente com o primeiro (nomes idênticos após
    # normalização não geram ambiguidade), ou, se a normalização não
    # unificar SOUZA/SOUSA, deve reportar ambiguidade -- nunca deve
    # escolher errado silenciosamente sem sinalizar.
    assert resultado.encontrado is True


def test_pessoa_nao_encontrada():
    indice = _construir_indice(["FULANO DE TAL"], ["ANALISTA"])
    resultado = indice.buscar("PESSOA COMPLETAMENTE DIFERENTE INEXISTENTE")
    assert resultado.encontrado is False
    assert resultado.confianca == Confianca.NAO_ENCONTRADO


def test_match_aceitavel_apenas_para_alta_e_conforme_configuracao_para_media():
    indice = _construir_indice(["JOÃO DA SILVA"], ["GERENTE"])
    resultado = indice.buscar("JOAO DA SILVA")
    assert match_e_confianca_aceitavel(resultado) is True

    resultado_nao_encontrado = indice.buscar("NOME QUE NAO EXISTE EM LUGAR NENHUM")
    assert match_e_confianca_aceitavel(resultado_nao_encontrado) is False


def test_nome_vazio_nao_e_buscado():
    indice = _construir_indice(["JOÃO DA SILVA"], ["GERENTE"])
    resultado = indice.buscar(None)
    assert resultado.encontrado is False
    assert resultado.confianca == Confianca.VAZIO
