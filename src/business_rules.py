"""
Regra de negócio: classificação de cargos como aprovador elegível.

Este módulo responde a UMA pergunta, e apenas uma:
"Dado o cargo de uma pessoa já identificada no RH, ela pode atuar como
aprovador de alta liderança (Diretor / VP / CEO)?"

Ele NÃO decide quem é a pessoa (isso é responsabilidade do módulo
`matching`) nem em que ordem os candidatos são avaliados (isso é
responsabilidade do `processor`). Essa separação é proposital: o
cargo nunca deve ser usado para "escolher" entre candidatos, apenas
para validar um candidato já determinado pela ordem do SAP.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import CONFIG_CARGOS
from .normalization import normalizar_texto, valor_vazio


@dataclass
class ClassificacaoCargo:
    elegivel: bool
    motivo: str


def classificar_cargo(cargo) -> ClassificacaoCargo:
    """Classifica um cargo/função como elegível (ou não) para ser
    aprovador, retornando também o motivo (para auditoria)."""

    if valor_vazio(cargo):
        return ClassificacaoCargo(elegivel=False, motivo="CARGO_VAZIO")

    cargo_normalizado = normalizar_texto(cargo)

    for padrao in CONFIG_CARGOS.padroes_excecao:
        if re.search(padrao, cargo_normalizado):
            return ClassificacaoCargo(
                elegivel=False,
                motivo=f"EXCECAO_NAO_ELEGIVEL ({padrao})",
            )

    for padrao in CONFIG_CARGOS.padroes_elegiveis:
        if re.search(padrao, cargo_normalizado):
            return ClassificacaoCargo(
                elegivel=True,
                motivo=f"CARGO_ELEGIVEL ({padrao})",
            )

    return ClassificacaoCargo(elegivel=False, motivo="CARGO_NAO_ELEGIVEL")


def eh_aprovador_valido(cargo) -> bool:
    """Atalho booleano sobre `classificar_cargo`, para uso simples em
    outras partes do código ou em testes rápidos."""

    return classificar_cargo(cargo).elegivel
