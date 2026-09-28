import io

from web.app import app


def test_pagina_inicial_carrega_interface_local():
    response = app.test_client().get("/")

    assert response.status_code == 200
    assert b"Arquivos de entrada" in response.data
    assert b"Planilhas processadas localmente" in response.data


def test_nao_inicia_sem_planilhas_obrigatorias():
    response = app.test_client().post("/api/runs", data={})

    assert response.status_code == 400
    assert "obrigatórios" in response.get_json()["error"]


def test_atualizar_depara_exige_base_rh():
    response = app.test_client().post(
        "/api/runs",
        data={
            "sap": (io.BytesIO(b"sap"), "sap.xlsx"),
            "depara": (io.BytesIO(b"depara"), "depara.xlsx"),
            "belvitur": (io.BytesIO(b"belvitur"), "belvitur.xlsx"),
            "atualizar_depara": "true",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "base RH" in response.get_json()["error"]


def test_producao_exige_autenticacao(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WEB_USERNAME", "operacao")
    monkeypatch.setenv("WEB_PASSWORD", "senha-de-teste")
    client = app.test_client()

    response = client.get("/")
    health_response = client.get("/health")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Basic")
    assert health_response.status_code == 200


def test_credenciais_corretas_acessam_aplicacao(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WEB_USERNAME", "operacao")
    monkeypatch.setenv("WEB_PASSWORD", "senha-de-teste")

    response = app.test_client().get("/", auth=("operacao", "senha-de-teste"))

    assert response.status_code == 200
