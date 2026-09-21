"""
Detecção flexível de colunas nas planilhas SAP e RH.

Este módulo existe para que o restante do sistema NÃO dependa de nomes
de coluna fixos como "Aprovador N1" ou "Nome Completo.2". Em vez disso,
ele procura por padrões (Aprovador + nível hierárquico, Nome, Função,
etc.) e só avança quando consegue identificar as colunas necessárias
com confiança razoável.

Se uma coluna obrigatória não puder ser identificada, uma exceção
`ColunaNaoEncontradaError` é levantada com uma mensagem detalhada:
qual coluna era esperada, quais foram encontradas e o que revisar.
Isso evita processar dados errados silenciosamente (ver princípio de
segurança do processo).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd
from unidecode import unidecode

from .config import ORDEM_NIVEIS_APROVADOR


class ColunaNaoEncontradaError(Exception):
    """Levantada quando uma coluna obrigatória não pôde ser
    identificada com segurança em uma planilha de entrada."""


def _normalizar_cabecalho(nome_coluna) -> str:
    """Normaliza o nome de uma coluna para facilitar comparação por
    padrões (maiúsculo, sem acento, sem pontuação, espaços colapsados)."""

    texto = str(nome_coluna)
    texto = texto.replace("\xa0", " ")
    texto = unidecode(texto)
    texto = texto.upper()
    texto = re.sub(r"[^A-Z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def limpar_nomes_colunas(df: pd.DataFrame) -> pd.DataFrame:
    """Remove espaços/caracteres invisíveis dos nomes de colunas de um
    DataFrame, preservando o texto original (só limpa, não normaliza
    para maiúsculo -- isso é feito à parte, na hora de procurar
    padrões)."""

    df = df.copy()
    df.columns = [str(col).replace("\xa0", " ").strip() for col in df.columns]
    return df


def _mensagem_erro(descricao_coluna: str, colunas_disponiveis: List[str], motivo: str) -> str:
    colunas_fmt = "\n".join(f"  - {c}" for c in colunas_disponiveis)
    return (
        f"\nERRO: não foi possível identificar com confiança a coluna "
        f"'{descricao_coluna}'.\n\n"
        f"Motivo: {motivo}\n\n"
        f"Colunas disponíveis na planilha:\n{colunas_fmt}\n\n"
        f"O que revisar: confirme se a planilha realmente contém essa "
        f"informação e se o nome da coluna guarda alguma semelhança "
        f"com o esperado (ex.: contém as palavras-chave usadas na "
        f"busca). Se o layout mudou de forma inesperada, ajuste os "
        f"padrões de busca em `src/column_mapping.py`."
    )


# ============================================================
# DETECÇÃO DE COLUNAS DA BASE SAP
# ============================================================

@dataclass
class NivelAprovador:
    """Representa um nível hierárquico de aprovador identificado na
    base SAP (ex.: N1, Sub., N2, ...)."""

    ordem: int
    rotulo: str
    coluna_codigo: Optional[str]
    coluna_nome: str


@dataclass
class MapeamentoSAP:
    coluna_centro_custo: str
    coluna_descricao_centro_custo: Optional[str]
    niveis: List[NivelAprovador]


_PADRAO_ROTULO_NIVEL = {
    "SUB": re.compile(r"\bSUB\b|\bSUBSTITUTO\b"),
    "N1": re.compile(r"\bN\s?1\b|\bNIVEL\s?1\b"),
    "N2": re.compile(r"\bN\s?2\b|\bNIVEL\s?2\b"),
    "N3": re.compile(r"\bN\s?3\b|\bNIVEL\s?3\b"),
    "N4": re.compile(r"\bN\s?4\b|\bNIVEL\s?4\b"),
    "N5": re.compile(r"\bN\s?5\b|\bNIVEL\s?5\b"),
    "N6": re.compile(r"\bN\s?6\b|\bNIVEL\s?6\b"),
}


def _identificar_rotulo_nivel(cabecalho_normalizado: str) -> Optional[str]:
    """Identifica qual nível hierárquico (N1, SUB, N2, ...) uma coluna
    representa, a partir do seu cabeçalho normalizado."""

    for rotulo, padrao in _PADRAO_ROTULO_NIVEL.items():
        if padrao.search(cabecalho_normalizado):
            return rotulo
    return None


def _detectar_coluna_centro_custo(df: pd.DataFrame) -> str:
    candidatas = []

    for coluna in df.columns:
        norm = _normalizar_cabecalho(coluna)
        if "CENTRO" in norm and "CUSTO" in norm and "DESCRI" not in norm:
            candidatas.append(coluna)

    if len(candidatas) == 1:
        return candidatas[0]

    if len(candidatas) > 1:
        # Prefere a coluna mais curta (normalmente o código, não a
        # descrição nem alguma variação com sufixo).
        candidatas.sort(key=len)
        return candidatas[0]

    raise ColunaNaoEncontradaError(
        _mensagem_erro(
            "Centro de Custo",
            list(df.columns),
            "nenhuma coluna contém simultaneamente as palavras "
            "'CENTRO' e 'CUSTO' (fora de uma coluna de descrição).",
        )
    )


def _detectar_coluna_descricao_centro_custo(df: pd.DataFrame) -> Optional[str]:
    for coluna in df.columns:
        norm = _normalizar_cabecalho(coluna)
        if "DESCRI" in norm and "CENTRO" in norm and "CUSTO" in norm:
            return coluna
    return None


def _detectar_colunas_aprovador_codigo(df: pd.DataFrame) -> Dict[str, str]:
    """Retorna um dicionário {rotulo_nivel: nome_da_coluna_codigo} para
    as colunas cujo cabeçalho contém 'APROVADOR'."""

    encontrados: Dict[str, str] = {}
    sem_rotulo: List[str] = []

    for coluna in df.columns:
        norm = _normalizar_cabecalho(coluna)

        if "APROVADOR" not in norm:
            continue

        rotulo = _identificar_rotulo_nivel(norm)

        if rotulo is None:
            sem_rotulo.append(coluna)
            continue

        if rotulo in encontrados:
            raise ColunaNaoEncontradaError(
                _mensagem_erro(
                    f"Aprovador {rotulo}",
                    list(df.columns),
                    f"mais de uma coluna parece representar o nível "
                    f"'{rotulo}' ('{encontrados[rotulo]}' e '{coluna}'). "
                    f"Não é possível decidir automaticamente qual usar.",
                )
            )

        encontrados[rotulo] = coluna

    # Fallback: uma única coluna "Aprovador" sem nenhum rótulo numérico
    # é tratada como N1, desde que N1 ainda não tenha sido encontrado.
    if sem_rotulo and "N1" not in encontrados and len(sem_rotulo) == 1:
        encontrados["N1"] = sem_rotulo[0]

    return encontrados


def _encontrar_coluna_nome_para(df: pd.DataFrame, coluna_codigo: str, usadas: set) -> str:
    """Encontra a coluna de nome associada a uma coluna de código de
    aprovador. Estratégia: procurar a coluna 'NOME'-like mais próxima
    (posicionalmente) da coluna de código, ainda não usada."""

    colunas = list(df.columns)
    indice_codigo = colunas.index(coluna_codigo)

    candidatas_nome = [
        (abs(i - indice_codigo), i, coluna)
        for i, coluna in enumerate(colunas)
        if coluna not in usadas and "NOME" in _normalizar_cabecalho(coluna)
    ]

    if not candidatas_nome:
        raise ColunaNaoEncontradaError(
            _mensagem_erro(
                f"Nome do aprovador correspondente a '{coluna_codigo}'",
                colunas,
                "não há nenhuma coluna disponível com 'NOME' no "
                "cabeçalho que ainda não tenha sido associada a outro "
                "nível de aprovador.",
            )
        )

    candidatas_nome.sort(key=lambda item: item[0])
    return candidatas_nome[0][2]


def detectar_mapeamento_sap(df: pd.DataFrame) -> MapeamentoSAP:
    """Detecta as colunas relevantes da base SAP: centro de custo,
    descrição e a sequência de níveis de aprovador (código + nome)."""

    df = limpar_nomes_colunas(df)

    coluna_centro_custo = _detectar_coluna_centro_custo(df)
    coluna_descricao = _detectar_coluna_descricao_centro_custo(df)

    colunas_codigo_por_nivel = _detectar_colunas_aprovador_codigo(df)

    if not colunas_codigo_por_nivel:
        raise ColunaNaoEncontradaError(
            _mensagem_erro(
                "Aprovador N1 (ou qualquer nível de aprovador)",
                list(df.columns),
                "nenhuma coluna contém a palavra 'APROVADOR'.",
            )
        )

    usadas: set = set(colunas_codigo_por_nivel.values())
    niveis: List[NivelAprovador] = []

    for rotulo, coluna_codigo in colunas_codigo_por_nivel.items():
        coluna_nome = _encontrar_coluna_nome_para(df, coluna_codigo, usadas)
        usadas.add(coluna_nome)

        niveis.append(
            NivelAprovador(
                ordem=ORDEM_NIVEIS_APROVADOR[rotulo],
                rotulo=rotulo,
                coluna_codigo=coluna_codigo,
                coluna_nome=coluna_nome,
            )
        )

    niveis.sort(key=lambda n: n.ordem)

    if not niveis:
        raise ColunaNaoEncontradaError(
            _mensagem_erro(
                "Sequência de aprovadores",
                list(df.columns),
                "nenhum nível hierárquico de aprovador pôde ser "
                "montado (código + nome).",
            )
        )

    return MapeamentoSAP(
        coluna_centro_custo=coluna_centro_custo,
        coluna_descricao_centro_custo=coluna_descricao,
        niveis=niveis,
    )


# ============================================================
# DETECÇÃO DE COLUNAS DA BASE RH
# ============================================================

@dataclass
class MapeamentoRH:
    coluna_nome: str
    coluna_cargo: str
    coluna_matricula: Optional[str]
    coluna_cpf: Optional[str]
    coluna_chefia: Optional[str]


_PALAVRAS_EXCLUIR_NOME = ("CENTRO", "UNIDADE", "EMPRESA", "CHEFIA", "ESTABELECIMENTO")


def _detectar_coluna_nome_rh(df: pd.DataFrame) -> str:
    exatas = [c for c in df.columns if _normalizar_cabecalho(c) == "NOME"]
    if exatas:
        return exatas[0]

    candidatas = [
        c
        for c in df.columns
        if "NOME" in _normalizar_cabecalho(c)
        and not any(palavra in _normalizar_cabecalho(c) for palavra in _PALAVRAS_EXCLUIR_NOME)
    ]

    if len(candidatas) == 1:
        return candidatas[0]

    if len(candidatas) > 1:
        candidatas.sort(key=len)
        return candidatas[0]

    raise ColunaNaoEncontradaError(
        _mensagem_erro(
            "Nome (do funcionário)",
            list(df.columns),
            "nenhuma coluna contém a palavra 'NOME' isolada de "
            "termos como CENTRO/UNIDADE/EMPRESA/CHEFIA.",
        )
    )


def _detectar_coluna_cargo_rh(df: pd.DataFrame) -> str:
    for palavra_chave in ("FUNCAO", "FUNÇÃO", "CARGO"):
        for coluna in df.columns:
            if palavra_chave in _normalizar_cabecalho(coluna):
                return coluna

    raise ColunaNaoEncontradaError(
        _mensagem_erro(
            "Função/Cargo",
            list(df.columns),
            "nenhuma coluna contém 'FUNÇÃO' ou 'CARGO'.",
        )
    )


def _detectar_coluna_opcional(df: pd.DataFrame, *palavras_chave: str) -> Optional[str]:
    for palavra_chave in palavras_chave:
        for coluna in df.columns:
            if palavra_chave in _normalizar_cabecalho(coluna):
                return coluna
    return None


def detectar_mapeamento_rh(df: pd.DataFrame) -> MapeamentoRH:
    """Detecta as colunas relevantes da base RH: nome, cargo/função e,
    quando disponíveis, identificadores auxiliares (matrícula, CPF,
    chefia imediata)."""

    df = limpar_nomes_colunas(df)

    coluna_nome = _detectar_coluna_nome_rh(df)
    coluna_cargo = _detectar_coluna_cargo_rh(df)
    coluna_matricula = _detectar_coluna_opcional(df, "MATRICULA", "MATRÍCULA")
    coluna_cpf = _detectar_coluna_opcional(df, "CPF")
    coluna_chefia = _detectar_coluna_opcional(df, "CHEFIA")

    return MapeamentoRH(
        coluna_nome=coluna_nome,
        coluna_cargo=coluna_cargo,
        coluna_matricula=coluna_matricula,
        coluna_cpf=coluna_cpf,
        coluna_chefia=coluna_chefia,
    )


# ============================================================
# DETECÇÃO DE COLUNAS DA BASE "DE-PARA" (SharePoint)
# ============================================================

@dataclass
class MapeamentoDePara:
    """Colunas da planilha "de-para" mantida pela área: cadastro
    curado que relaciona o ID SAP de cada possível aprovador ao seu
    cargo/função e gestor direto atuais. É a fonte primária de cargo
    (chave exata, ID SAP), muito mais confiável que qualquer matching
    por nome."""

    coluna_sap_id: str
    coluna_nome_sap: Optional[str]
    coluna_nome_rh: Optional[str]
    coluna_cargo: str
    coluna_gestor: Optional[str]
    coluna_email: Optional[str]
    coluna_cpf: Optional[str]


def _sem_espacos(cabecalho_normalizado: str) -> str:
    return cabecalho_normalizado.replace(" ", "")


def _detectar_coluna_sap_id(df: pd.DataFrame) -> str:
    candidatas = [
        c for c in df.columns
        if "SAP" in _normalizar_cabecalho(c) and "ID" in _normalizar_cabecalho(c)
    ]
    if len(candidatas) == 1:
        return candidatas[0]
    if len(candidatas) > 1:
        candidatas.sort(key=len)
        return candidatas[0]

    raise ColunaNaoEncontradaError(
        _mensagem_erro(
            "ID SAP do aprovador (de-para)",
            list(df.columns),
            "nenhuma coluna contém simultaneamente as palavras 'SAP' e 'ID'.",
        )
    )


def _detectar_coluna_cargo_depara(df: pd.DataFrame) -> str:
    candidatas = [c for c in df.columns if "CARGO" in _normalizar_cabecalho(c)]
    if len(candidatas) == 1:
        return candidatas[0]
    if len(candidatas) > 1:
        candidatas.sort(key=len)
        return candidatas[0]

    raise ColunaNaoEncontradaError(
        _mensagem_erro(
            "Cargo (de-para)",
            list(df.columns),
            "nenhuma coluna contém a palavra 'CARGO'.",
        )
    )


def _detectar_coluna_nome_qualificado(df: pd.DataFrame, qualificador: str) -> Optional[str]:
    """Procura uma coluna de nome desambiguada por um qualificador
    (ex.: 'SAP' ou 'RH'), como em 'Nome Completo - Aprovador SAP' /
    'Nome Completo - RH'."""

    candidatas = [
        c
        for c in df.columns
        if "NOME" in _normalizar_cabecalho(c) and qualificador in _normalizar_cabecalho(c)
    ]
    if len(candidatas) >= 1:
        candidatas.sort(key=len)
        return candidatas[0]
    return None


def detectar_mapeamento_depara(df: pd.DataFrame) -> MapeamentoDePara:
    """Detecta as colunas relevantes da base "de-para": ID SAP (chave
    primária), cargo e, quando disponíveis, nome (SAP/RH), gestor
    direto, e-mail e CPF."""

    df = limpar_nomes_colunas(df)

    coluna_sap_id = _detectar_coluna_sap_id(df)
    coluna_cargo = _detectar_coluna_cargo_depara(df)
    coluna_nome_sap = _detectar_coluna_nome_qualificado(df, "SAP")
    coluna_nome_rh = _detectar_coluna_nome_qualificado(df, "RH")
    coluna_gestor = _detectar_coluna_opcional(df, "GESTOR")
    coluna_cpf = _detectar_coluna_opcional(df, "CPF")

    coluna_email = None
    for coluna in df.columns:
        if "MAIL" in _sem_espacos(_normalizar_cabecalho(coluna)):
            coluna_email = coluna
            break

    return MapeamentoDePara(
        coluna_sap_id=coluna_sap_id,
        coluna_nome_sap=coluna_nome_sap,
        coluna_nome_rh=coluna_nome_rh,
        coluna_cargo=coluna_cargo,
        coluna_gestor=coluna_gestor,
        coluna_email=coluna_email,
        coluna_cpf=coluna_cpf,
    )


# ============================================================
# DETECÇÃO DE COLUNAS DA PLANILHA DA BELVITUR
# ============================================================

@dataclass
class MapeamentoBelvitur:
    """Colunas da planilha enviada pela Belvitur, que este processo
    atualiza com o aprovador calculado e a coluna de Ação."""

    coluna_centro_custo: str
    coluna_descricao_centro_custo: Optional[str]
    coluna_aprovador_atual: str


def _detectar_coluna_aprovador_atual(df: pd.DataFrame) -> str:
    # Preferência 1: cabeçalho normalizado igual a "APROVADOR" (caso
    # exato mais comum, ex.: "Aprovador").
    exatas = [c for c in df.columns if _normalizar_cabecalho(c) == "APROVADOR"]
    if exatas:
        return exatas[0]

    # Preferência 2: contém "APROVADOR", mas exclui variações que
    # claramente não são o aprovador atual (colunas já calculadas por
    # uma execução anterior desta própria automação, ex.: "APROVADOR
    # SAP", "APROVADOR DO APROVADOR").
    candidatas = [
        c
        for c in df.columns
        if "APROVADOR" in _normalizar_cabecalho(c)
        and "SAP" not in _normalizar_cabecalho(c)
        and "GESTOR" not in _normalizar_cabecalho(c)
        and _normalizar_cabecalho(c).count("APROVADOR") == 1
    ]
    if len(candidatas) == 1:
        return candidatas[0]
    if len(candidatas) > 1:
        candidatas.sort(key=len)
        return candidatas[0]

    raise ColunaNaoEncontradaError(
        _mensagem_erro(
            "Aprovador atual (planilha da Belvitur)",
            list(df.columns),
            "nenhuma coluna contém a palavra 'APROVADOR' sem ser uma "
            "coluna já calculada por uma execução anterior (ex.: "
            "'APROVADOR SAP').",
        )
    )


def detectar_mapeamento_belvitur(df: pd.DataFrame) -> MapeamentoBelvitur:
    """Detecta as colunas relevantes da planilha da Belvitur: Centro
    de Custo, descrição (opcional) e o aprovador atualmente cadastrado."""

    df = limpar_nomes_colunas(df)

    coluna_centro_custo = _detectar_coluna_centro_custo(df)
    coluna_descricao = _detectar_coluna_descricao_centro_custo(df)
    coluna_aprovador_atual = _detectar_coluna_aprovador_atual(df)

    return MapeamentoBelvitur(
        coluna_centro_custo=coluna_centro_custo,
        coluna_descricao_centro_custo=coluna_descricao,
        coluna_aprovador_atual=coluna_aprovador_atual,
    )
