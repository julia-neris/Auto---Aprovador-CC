"""
Resolução de candidatos a aprovador: "quem, no cadastro de referência,
é esta pessoa citada no nível N1/Sub./N2/N3 do SAP?".

Este módulo NÃO decide se a pessoa é elegível para ser aprovadora
(isso é `business_rules`) nem em que ordem os candidatos são avaliados
(isso é `processor`). Ele apenas resolve identidade + cargo, com dois
níveis de estratégia, do mais para o menos confiável:

    Tier 0: busca exata pelo ID SAP na base "de-para" (SharePoint).
        A base SAP já traz o ID SAP de cada candidato nas colunas de
        aprovador; a base de-para é indexada por esse mesmo ID. Isso
        torna a busca um dicionário O(1), exata e sem ambiguidade --
        e é o caminho usado para a grande maioria dos candidatos.

    Tier 1: fallback por matching de nome na base RH completa.
        Usado apenas quando o ID SAP do candidato não está cadastrado
        no de-para (cadastro "órfão", ex.: pessoa nova, ou de-para
        desatualizado). Reaproveita o motor de matching por nome
        (`matching.IndiceRH`), que já trata variações de nome, fuzzy
        matching e ambiguidade.

Separar os dois tiers em um resolvedor único mantém o restante do
sistema auditável: cada resultado carrega o método usado
(DE_PARA_SAP_ID_EXATO vs. RH_FALLBACK_<método original>), o que
permite explicar qualquer decisão automática.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import CONFIG_MATCHING, Confianca
from .depara import IndiceDePara
from .matching import IndiceRH, ResultadoMatch
from .normalization import valor_vazio


@dataclass
class ResultadoResolucao:
    nome_sap: str
    sap_id: str
    encontrado: bool
    confianca: str
    metodo: str
    motivo: str

    nome_encontrado: Optional[str] = None
    cargo: Optional[str] = None
    gestor: Optional[str] = None
    email: Optional[str] = None
    matricula: Optional[str] = None

    score_final: Optional[float] = None


def _resultado_vazio(sap_id, nome_sap) -> ResultadoResolucao:
    return ResultadoResolucao(
        nome_sap=str(nome_sap) if not valor_vazio(nome_sap) else "",
        sap_id=str(sap_id) if not valor_vazio(sap_id) else "",
        encontrado=False,
        confianca=Confianca.VAZIO,
        metodo="CANDIDATO_VAZIO",
        motivo="Candidato vazio na base SAP.",
    )


def _converter_resultado_rh(resultado_rh: ResultadoMatch, sap_id) -> ResultadoResolucao:
    return ResultadoResolucao(
        nome_sap=resultado_rh.nome_sap,
        sap_id=str(sap_id) if not valor_vazio(sap_id) else "",
        encontrado=resultado_rh.encontrado,
        confianca=resultado_rh.confianca,
        metodo=f"RH_FALLBACK_{resultado_rh.metodo}",
        motivo=resultado_rh.motivo,
        nome_encontrado=resultado_rh.nome_rh,
        cargo=resultado_rh.cargo_rh,
        gestor=resultado_rh.chefia_rh,
        matricula=resultado_rh.matricula_rh,
        score_final=resultado_rh.score_final,
    )


class ResolvedorAprovador:
    """Combina o índice de-para (Tier 0, exato por ID SAP) com um
    índice RH de fallback (Tier 1, por nome), opcional."""

    def __init__(self, indice_depara: IndiceDePara, indice_rh_fallback: Optional[IndiceRH] = None):
        self._indice_depara = indice_depara
        self._indice_rh_fallback = indice_rh_fallback

    def resolver(self, sap_id, nome_sap) -> ResultadoResolucao:
        sap_id_vazio = valor_vazio(sap_id)
        nome_vazio = valor_vazio(nome_sap)

        if sap_id_vazio and nome_vazio:
            return _resultado_vazio(sap_id, nome_sap)

        # ---- Tier 0: de-para por ID SAP exato -----------------------
        if not sap_id_vazio:
            info = self._indice_depara.buscar_por_sap_id(sap_id)
            if info is not None:
                nome_encontrado = info.nome_rh or info.nome_sap
                return ResultadoResolucao(
                    nome_sap=str(nome_sap) if not nome_vazio else str(sap_id),
                    sap_id=str(sap_id),
                    encontrado=True,
                    confianca=Confianca.ALTA,
                    metodo="DE_PARA_SAP_ID_EXATO",
                    motivo=(
                        "ID SAP localizado diretamente na base de-para "
                        "(chave exata, sem necessidade de matching por nome)."
                    ),
                    nome_encontrado=nome_encontrado,
                    cargo=info.cargo,
                    gestor=info.gestor,
                    email=info.email,
                    score_final=100.0,
                )

        # ---- Tier 1: fallback por nome no RH completo ---------------
        # Só é acionado para IDs SAP "órfãos" (não cadastrados no
        # de-para) -- volume baixo, adequado para matching por nome
        # sem custo de performance relevante sobre as 91 mil linhas.
        if self._indice_rh_fallback is not None and not nome_vazio:
            resultado_rh = self._indice_rh_fallback.buscar(nome_sap)
            return _converter_resultado_rh(resultado_rh, sap_id)

        if not sap_id_vazio:
            motivo = (
                f"ID SAP '{sap_id}' não cadastrado na base de-para e "
                f"nenhuma base de fallback (RH completo) foi configurada "
                f"ou o nome do candidato está vazio para tentar matching."
            )
        else:
            motivo = "Candidato sem ID SAP e sem nome suficiente para matching de fallback."

        return ResultadoResolucao(
            nome_sap=str(nome_sap) if not nome_vazio else "",
            sap_id=str(sap_id) if not sap_id_vazio else "",
            encontrado=False,
            confianca=Confianca.NAO_ENCONTRADO,
            metodo="NAO_ENCONTRADO_DE_PARA",
            motivo=motivo,
        )


def resolucao_e_confianca_aceitavel(resultado: ResultadoResolucao) -> bool:
    """Mesma regra de segurança do matching por nome (ver
    `matching.match_e_confianca_aceitavel`), aplicada ao resultado
    unificado do resolvedor: só aceita automaticamente ALTA, ou MÉDIA
    quando a configuração permitir."""

    if not resultado.encontrado:
        return False

    if resultado.confianca == Confianca.ALTA:
        return True

    if resultado.confianca == Confianca.MEDIA:
        return CONFIG_MATCHING.aceitar_media_automaticamente

    return False
