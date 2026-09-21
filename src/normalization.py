"""
Normalização de textos e nomes.

Estas funções são a base para toda comparação entre nomes do SAP e do
RH. O objetivo é remover diferenças "acidentais" (acentos, espaços
duplicados, caixa, caracteres invisíveis) sem alterar o significado do
nome.
"""

from __future__ import annotations

import re
from typing import Iterable, List

import pandas as pd
from unidecode import unidecode

from .config import CONFIG_MATCHING

_CARACTERES_INVISIVEIS = ("\xa0", "\u200b", "\ufeff")


def valor_vazio(valor) -> bool:
    """Retorna True quando o valor é nulo, None ou contém apenas espaços."""

    if valor is None:
        return True

    try:
        if pd.isna(valor):
            return True
    except (TypeError, ValueError):
        pass

    return str(valor).strip() == ""


def normalizar_texto(valor) -> str:
    """Normalização genérica de um texto: remove acentos, caixa alta,
    espaços duplicados e caracteres invisíveis comuns em exportações do
    SAP/Excel."""

    if valor_vazio(valor):
        return ""

    texto = str(valor)

    for caractere in _CARACTERES_INVISIVEIS:
        texto = texto.replace(caractere, " " if caractere == "\xa0" else "")

    texto = unidecode(texto)
    texto = texto.upper()
    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


def normalizar_nome(nome) -> str:
    """Normaliza um nome de pessoa para comparação.

    Além da normalização genérica, remove qualquer caractere que não
    seja letra, número ou espaço (pontuação, hífen, etc.), pois nomes
    às vezes vêm com hífens, pontos ou abreviações estranhas.
    """

    texto = normalizar_texto(nome)

    if not texto:
        return ""

    texto = re.sub(r"[^A-Z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


def tokenizar_nome(nome_normalizado: str, ignorar_palavras: Iterable[str] | None = None) -> List[str]:
    """Quebra um nome já normalizado em tokens, removendo preposições
    comuns (DA, DE, DO, ...) que não ajudam a diferenciar pessoas."""

    if ignorar_palavras is None:
        ignorar_palavras = CONFIG_MATCHING.palavras_ignoradas_em_nomes

    ignorar = set(ignorar_palavras)

    if not nome_normalizado:
        return []

    return [token for token in nome_normalizado.split() if token not in ignorar]
