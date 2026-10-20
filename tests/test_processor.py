import pandas as pd

from src.column_mapping import MapeamentoDePara, MapeamentoRH
from src.depara import IndiceDePara
from src.matching import IndiceRH
from src.processor import (
    EventoAuditoria,
    ResultadoLinha,
    STATUS_APROVADOR_ENCONTRADO,
    STATUS_CARGO_NAO_ELEGIVEL,
    STATUS_NAO_ENCONTRADO_RH,
    STATUS_SEM_APROVADOR,
    _dataclasses_para_dataframe,
    _processar_linha,
)
from src.resolver import ResolvedorAprovador


def _construir_resolvedor(pessoas):
    """pessoas: lista de (nome, cargo).

    Os testes de negócio (regra de sequência SAP) não dependem de ID
    SAP -- por isso o de-para (Tier 0) é montado vazio, e a resolução
    cai direto no fallback por nome via RH (Tier 1), que é o mesmo
    motor de matching testado em `test_matching.py`."""

    df_rh = pd.DataFrame(
        {
            "NOME": [p[0] for p in pessoas],
            "CARGO": [p[1] for p in pessoas],
            "MATRICULA": [str(i) for i in range(len(pessoas))],
            "CPF": [str(i).zfill(11) for i in range(len(pessoas))],
        }
    )
    mapeamento_rh = MapeamentoRH(
        coluna_nome="NOME",
        coluna_cargo="CARGO",
        coluna_matricula="MATRICULA",
        coluna_cpf="CPF",
        coluna_chefia=None,
    )
    indice_rh = IndiceRH(df_rh, mapeamento_rh)

    df_depara_vazio = pd.DataFrame({"SAP ID": [], "CARGO": []})
    mapeamento_depara = MapeamentoDePara(
        coluna_sap_id="SAP ID",
        coluna_cargo="CARGO",
        coluna_nome_sap=None,
        coluna_nome_rh=None,
        coluna_gestor=None,
        coluna_email=None,
        coluna_cpf=None,
    )
    indice_depara = IndiceDePara(df_depara_vazio, mapeamento_depara)

    return ResolvedorAprovador(indice_depara, indice_rh)


def _processar(resolvedor, valores_por_nivel_nome):
    """`valores_por_nivel_nome`: lista de (rotulo, nome) -- sem ID SAP,
    já que os testes de regra de negócio exercitam apenas o fallback
    por nome (Tier 1). Convertido para a tupla (rotulo, sap_id, nome)
    esperada por `_processar_linha`, com sap_id sempre vazio."""

    valores_por_nivel = [(rotulo, None, nome) for rotulo, nome in valores_por_nivel_nome]
    eventos = []
    return (
        _processar_linha("CC1", "Centro Teste", valores_por_nivel, resolvedor, eventos),
        eventos,
    )


def test_conversao_por_colunas_preserva_dataframe_legado():
    resultados = [
        ResultadoLinha("CC1", "Centro 1", STATUS_APROVADOR_ENCONTRADO, "OK", aprovador_nome="Maria"),
        ResultadoLinha("CC2", None, STATUS_SEM_APROVADOR, "Sem candidato"),
    ]
    auditoria = [
        EventoAuditoria("CC1", "Centro 1", "N1", "123", "Maria", "Maria", "DIRETOR", "EXATO", 100.0, "ALTA", True, "CARGO_ELEGIVEL", True),
        EventoAuditoria("CC2", None, "N1", "", "", None, None, "-", None, "VAZIO", None, "CANDIDATO_VAZIO", False),
    ]

    for registros in (resultados, auditoria):
        legado = pd.DataFrame([registro.__dict__ for registro in registros])
        otimizado = _dataclasses_para_dataframe(registros)
        pd.testing.assert_frame_equal(otimizado, legado)


def test_1_n1_vazio_n2_diretor_seleciona_n2():
    resolvedor = _construir_resolvedor([("MARIA SOUZA", "DIRETOR")])
    resultado, _ = _processar(
        resolvedor, [("N1", None), ("N2", "MARIA SOUZA")]
    )
    assert resultado.status == STATUS_APROVADOR_ENCONTRADO
    assert resultado.nivel_sap_origem == "N2"
    assert resultado.aprovador_nome == "MARIA SOUZA"


def test_2_n1_gerente_n2_diretor_seleciona_n2():
    resolvedor = _construir_resolvedor([("JOAO PEREIRA", "GERENTE"), ("MARIA SOUZA", "DIRETOR")])
    resultado, _ = _processar(
        resolvedor, [("N1", "JOAO PEREIRA"), ("N2", "MARIA SOUZA")]
    )
    assert resultado.status == STATUS_APROVADOR_ENCONTRADO
    assert resultado.nivel_sap_origem == "N2"
    assert resultado.aprovador_nome == "MARIA SOUZA"


def test_3_n1_diretor_n2_ceo_seleciona_n1_ordem_e_soberana():
    resolvedor = _construir_resolvedor([("MARIA SOUZA", "DIRETOR"), ("JOAO PEREIRA", "CEO")])
    resultado, _ = _processar(
        resolvedor, [("N1", "MARIA SOUZA"), ("N2", "JOAO PEREIRA")]
    )
    assert resultado.status == STATUS_APROVADOR_ENCONTRADO
    assert resultado.nivel_sap_origem == "N1"
    assert resultado.aprovador_nome == "MARIA SOUZA"


def test_4_n1_gerente_n2_vp_seleciona_n2():
    resolvedor = _construir_resolvedor([("JOAO PEREIRA", "GERENTE"), ("MARIA SOUZA", "VP")])
    resultado, _ = _processar(
        resolvedor, [("N1", "JOAO PEREIRA"), ("N2", "MARIA SOUZA")]
    )
    assert resultado.status == STATUS_APROVADOR_ENCONTRADO
    assert resultado.nivel_sap_origem == "N2"


def test_5_n1_nao_encontrado_n2_diretor_continua_para_n2():
    resolvedor = _construir_resolvedor([("MARIA SOUZA", "DIRETOR")])
    resultado, _ = _processar(
        resolvedor, [("N1", "PESSOA COMPLETAMENTE INEXISTENTE XYZ"), ("N2", "MARIA SOUZA")]
    )
    assert resultado.status == STATUS_APROVADOR_ENCONTRADO
    assert resultado.nivel_sap_origem == "N2"


def test_9_todos_vazios_ate_n3_seleciona_n3():
    resolvedor = _construir_resolvedor([("CARLOS LIMA", "DIRETOR")])
    resultado, _ = _processar(
        resolvedor,
        [("N1", None), ("SUB", ""), ("N2", None), ("N3", "CARLOS LIMA")],
    )
    assert resultado.status == STATUS_APROVADOR_ENCONTRADO
    assert resultado.nivel_sap_origem == "N3"


def test_10_nenhum_candidato_valido_sem_aprovador():
    resolvedor = _construir_resolvedor([("JOAO PEREIRA", "GERENTE"), ("CARLOS LIMA", "ANALISTA")])
    resultado, _ = _processar(
        resolvedor, [("N1", "JOAO PEREIRA"), ("N2", "CARLOS LIMA")]
    )
    assert resultado.status == STATUS_CARGO_NAO_ELEGIVEL


def test_todos_os_niveis_vazios_marca_sem_aprovador():
    resolvedor = _construir_resolvedor([("MARIA SOUZA", "DIRETOR")])
    resultado, _ = _processar(resolvedor, [("N1", None), ("SUB", ""), ("N2", None)])
    assert resultado.status == STATUS_SEM_APROVADOR


def test_candidato_nao_encontrado_em_lugar_nenhum_reporta_nao_encontrado():
    resolvedor = _construir_resolvedor([("MARIA SOUZA", "DIRETOR")])
    resultado, _ = _processar(
        resolvedor, [("N1", "NOME QUE NAO EXISTE NO RH DE JEITO NENHUM")]
    )
    assert resultado.status == STATUS_NAO_ENCONTRADO_RH


def test_sap_id_exato_no_de_para_tem_prioridade_sobre_nome():
    """Quando o ID SAP do candidato está cadastrado no de-para, a
    resolução usa Tier 0 (exata), mesmo que o nome divirja um pouco do
    valor exibido na base SAP."""

    df_depara = pd.DataFrame(
        {
            "SAP ID": ["ABC123"],
            "Nome Completo - Aprovador SAP": ["MARIA SOUZA"],
            "CARGO": ["DIRETOR"],
        }
    )
    mapeamento_depara = MapeamentoDePara(
        coluna_sap_id="SAP ID",
        coluna_cargo="CARGO",
        coluna_nome_sap="Nome Completo - Aprovador SAP",
        coluna_nome_rh=None,
        coluna_gestor=None,
        coluna_email=None,
        coluna_cpf=None,
    )
    indice_depara = IndiceDePara(df_depara, mapeamento_depara)
    resolvedor = ResolvedorAprovador(indice_depara, indice_rh_fallback=None)

    eventos = []
    resultado = _processar_linha(
        "CC1", "Centro Teste", [("N1", "ABC123", "MARIA SOUZA")], resolvedor, eventos
    )

    assert resultado.status == STATUS_APROVADOR_ENCONTRADO
    assert resultado.metodo_match == "DE_PARA_SAP_ID_EXATO"
    assert resultado.aprovador_sap_id == "ABC123"
