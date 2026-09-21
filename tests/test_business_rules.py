from src.business_rules import classificar_cargo, eh_aprovador_valido


def test_diretor_simples_e_valido():
    assert eh_aprovador_valido("DIRETOR") is True


def test_diretor_executivo_e_valido():
    assert eh_aprovador_valido("DIRETOR EXECUTIVO") is True


def test_vice_presidente_e_valido():
    assert eh_aprovador_valido("VICE PRESIDENTE") is True
    assert eh_aprovador_valido("VICE-PRESIDENTE") is True


def test_vp_e_valido():
    assert eh_aprovador_valido("VP") is True


def test_ceo_e_valido():
    assert eh_aprovador_valido("CEO") is True


def test_gerente_nao_e_valido():
    assert eh_aprovador_valido("GERENTE") is False


def test_assist_diretoria_nao_e_valido():
    # Teste 8 do escopo: "ASSIST. DIRETORIA" não deve ser considerado Diretor.
    assert eh_aprovador_valido("ASSIST. DIRETORIA") is False


def test_diretoria_sozinho_nao_e_confundido_com_diretor():
    # "DIRETORIA" não é a mesma palavra que "DIRETOR".
    assert eh_aprovador_valido("DIRETORIA EXECUTIVA") is False


def test_cargo_vazio_nao_e_valido():
    assert eh_aprovador_valido("") is False
    assert eh_aprovador_valido(None) is False


def test_motivo_e_auditavel():
    resultado = classificar_cargo("ASSIST. DIRETORIA")
    assert resultado.elegivel is False
    assert "EXCECAO" in resultado.motivo

    resultado = classificar_cargo("DIRETOR EXECUTIVO")
    assert resultado.elegivel is True
    assert "CARGO_ELEGIVEL" in resultado.motivo
