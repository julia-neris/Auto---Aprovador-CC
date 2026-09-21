"""
Processamento linha a linha da base SAP.

Este é o módulo que orquestra a regra de negócio principal:

    DADOS -> RESOLUÇÃO (de-para/RH) -> REGRA DE NEGÓCIO -> DECISÃO -> AUDITORIA

Para cada Centro de Custo, percorre os candidatos a aprovador NA ORDEM
em que aparecem no SAP (essa ordem é soberana, nunca é reordenada pelo
cargo), limitado ao nível `config.MAX_NIVEL_PROCESSAMENTO` (por padrão,
N3 -- ver regra de negócio confirmada com a área). Para cada candidato:

    1. Ignora se vazio (sem ID SAP e sem nome).
    2. Resolve a identidade/cargo do candidato (módulo `resolver`):
       primeiro por ID SAP exato na base de-para, com fallback por
       nome na base RH completa apenas para IDs não cadastrados.
    3. Se a resolução não tiver confiança suficiente, ou for ambígua,
       registra o motivo e passa para o próximo candidato.
    4. Se resolvido, verifica se o cargo é elegível (`business_rules`).
    5. Se não for elegível, passa para o próximo candidato.
    6. Se for elegível e a resolução for confiável, esse é o aprovador
       final -- para o processamento daquela linha.

Se nenhum candidato for válido, a linha é marcada para revisão manual
com o status mais adequado (ver `_status_final_sem_sucesso`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from .business_rules import classificar_cargo
from .column_mapping import MapeamentoSAP, NivelAprovador
from .config import MAX_NIVEL_PROCESSAMENTO
from .normalization import valor_vazio
from .resolver import ResolvedorAprovador, ResultadoResolucao, resolucao_e_confianca_aceitavel


STATUS_APROVADOR_ENCONTRADO = "APROVADOR_ENCONTRADO"
STATUS_SEM_APROVADOR = "SEM_APROVADOR"
STATUS_NAO_ENCONTRADO_RH = "NAO_ENCONTRADO_RH"
STATUS_CARGO_NAO_ELEGIVEL = "CARGO_NAO_ELEGIVEL"
STATUS_MATCH_BAIXA_CONFIANCA = "MATCH_BAIXA_CONFIANCA"
STATUS_MATCH_AMBIGUO = "MATCH_AMBIGUO"


@dataclass
class EventoAuditoria:
    centro_custo: object
    descricao_centro_custo: object
    nivel_sap: str
    sap_id_buscado: str
    nome_buscado_sap: str
    nome_encontrado: Optional[str]
    cargo: Optional[str]
    metodo: str
    score_final: Optional[float]
    confianca: str
    elegivel: Optional[bool]
    motivo: str
    selecionado: bool


@dataclass
class ResultadoLinha:
    centro_custo: object
    descricao_centro_custo: object
    status: str
    motivo: str
    aprovador_nome: Optional[str] = None
    aprovador_cargo: Optional[str] = None
    aprovador_gestor: Optional[str] = None
    aprovador_email: Optional[str] = None
    aprovador_sap_id: Optional[str] = None
    nivel_sap_origem: Optional[str] = None
    nome_sap_original: Optional[str] = None
    nome_rh_encontrado: Optional[str] = None
    metodo_match: Optional[str] = None
    score_match: Optional[float] = None
    confianca_match: Optional[str] = None
    observacao: str = ""


def _status_final_sem_sucesso(eventos_linha: List[EventoAuditoria]) -> tuple[str, str]:
    """Decide o status/motivo final de uma linha em que nenhum
    candidato resultou em aprovador selecionado.

    Prioridade (do sinal que mais precisa de atenção humana para o
    menos crítico): AMBÍGUO > BAIXA CONFIANÇA > NÃO ENCONTRADO NO
    CADASTRO > CARGO NÃO ELEGÍVEL > SEM CANDIDATOS (todos os níveis
    processados estavam vazios).
    """

    eventos_com_candidato = [e for e in eventos_linha if e.motivo != "CANDIDATO_VAZIO"]

    if not eventos_com_candidato:
        return (
            STATUS_SEM_APROVADOR,
            "Nenhum nível de aprovador (até o limite configurado) possui "
            "candidato preenchido.",
        )

    if any(e.confianca == "AMBIGUA" for e in eventos_com_candidato):
        return (
            STATUS_MATCH_AMBIGUO,
            "Ao menos um candidato correspondeu a mais de uma pessoa com "
            "pontuações muito próximas; requer revisão humana.",
        )

    if any(e.confianca == "BAIXA" for e in eventos_com_candidato):
        return (
            STATUS_MATCH_BAIXA_CONFIANCA,
            "Ao menos um candidato teve match aproximado, mas com "
            "confiança insuficiente para aceite automático.",
        )

    if any(e.nome_encontrado for e in eventos_com_candidato):
        return (
            STATUS_CARGO_NAO_ELEGIVEL,
            "Todos os candidatos localizados possuem cargo não elegível "
            "para aprovação (não são Diretor/VP/CEO).",
        )

    return (
        STATUS_NAO_ENCONTRADO_RH,
        "Nenhum dos candidatos preenchidos foi localizado no de-para nem "
        "no RH (fallback).",
    )


def _processar_linha(
    centro_custo,
    descricao_centro_custo,
    valores_por_nivel: List[tuple],
    resolvedor: ResolvedorAprovador,
    eventos_auditoria: List[EventoAuditoria],
) -> ResultadoLinha:
    """`valores_por_nivel` é uma lista de (rotulo_nivel, sap_id, nome)
    já limitada ao `MAX_NIVEL_PROCESSAMENTO` pelo chamador."""

    eventos_linha: List[EventoAuditoria] = []

    for nivel_rotulo, sap_id_candidato, nome_candidato in valores_por_nivel:
        if valor_vazio(sap_id_candidato) and valor_vazio(nome_candidato):
            eventos_linha.append(
                EventoAuditoria(
                    centro_custo=centro_custo,
                    descricao_centro_custo=descricao_centro_custo,
                    nivel_sap=nivel_rotulo,
                    sap_id_buscado="",
                    nome_buscado_sap="",
                    nome_encontrado=None,
                    cargo=None,
                    metodo="-",
                    score_final=None,
                    confianca="VAZIO",
                    elegivel=None,
                    motivo="CANDIDATO_VAZIO",
                    selecionado=False,
                )
            )
            continue

        resultado: ResultadoResolucao = resolvedor.resolver(sap_id_candidato, nome_candidato)

        if not resolucao_e_confianca_aceitavel(resultado):
            eventos_linha.append(
                EventoAuditoria(
                    centro_custo=centro_custo,
                    descricao_centro_custo=descricao_centro_custo,
                    nivel_sap=nivel_rotulo,
                    sap_id_buscado=resultado.sap_id,
                    nome_buscado_sap=resultado.nome_sap,
                    nome_encontrado=resultado.nome_encontrado,
                    cargo=resultado.cargo,
                    metodo=resultado.metodo,
                    score_final=resultado.score_final,
                    confianca=resultado.confianca,
                    elegivel=None,
                    motivo=resultado.motivo,
                    selecionado=False,
                )
            )
            continue

        classificacao = classificar_cargo(resultado.cargo)

        eventos_linha.append(
            EventoAuditoria(
                centro_custo=centro_custo,
                descricao_centro_custo=descricao_centro_custo,
                nivel_sap=nivel_rotulo,
                sap_id_buscado=resultado.sap_id,
                nome_buscado_sap=resultado.nome_sap,
                nome_encontrado=resultado.nome_encontrado,
                cargo=resultado.cargo,
                metodo=resultado.metodo,
                score_final=resultado.score_final,
                confianca=resultado.confianca,
                elegivel=classificacao.elegivel,
                motivo=classificacao.motivo,
                selecionado=classificacao.elegivel,
            )
        )

        if classificacao.elegivel:
            eventos_auditoria.extend(eventos_linha)

            return ResultadoLinha(
                centro_custo=centro_custo,
                descricao_centro_custo=descricao_centro_custo,
                status=STATUS_APROVADOR_ENCONTRADO,
                motivo=f"Primeiro candidato elegível na ordem SAP (nível {nivel_rotulo}).",
                aprovador_nome=resultado.nome_encontrado,
                aprovador_cargo=resultado.cargo,
                aprovador_gestor=resultado.gestor,
                aprovador_email=resultado.email,
                aprovador_sap_id=resultado.sap_id,
                nivel_sap_origem=nivel_rotulo,
                nome_sap_original=resultado.nome_sap,
                nome_rh_encontrado=resultado.nome_encontrado,
                metodo_match=resultado.metodo,
                score_match=resultado.score_final,
                confianca_match=resultado.confianca,
            )

    eventos_auditoria.extend(eventos_linha)

    status, motivo = _status_final_sem_sucesso(eventos_linha)

    return ResultadoLinha(
        centro_custo=centro_custo,
        descricao_centro_custo=descricao_centro_custo,
        status=status,
        motivo=motivo,
    )


def processar_base_sap(
    df_sap: pd.DataFrame,
    mapeamento: MapeamentoSAP,
    resolvedor: ResolvedorAprovador,
    logger: logging.Logger,
    intervalo_log: int = 5000,
    nivel_maximo: int = MAX_NIVEL_PROCESSAMENTO,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Processa todas as linhas da base SAP e retorna
    (df_resultado, df_auditoria).

    `nivel_maximo` limita quais níveis da sequência SAP são
    considerados (por padrão, até N3 -- ver
    `config.MAX_NIVEL_PROCESSAMENTO`). Níveis com `ordem > nivel_maximo`
    nem chegam a ser lidos do DataFrame, o que também poupa memória/
    tempo em bases muito largas.
    """

    niveis_ordenados: List[NivelAprovador] = sorted(
        (n for n in mapeamento.niveis if n.ordem <= nivel_maximo),
        key=lambda n: n.ordem,
    )

    if not niveis_ordenados:
        raise ValueError(
            "Nenhum nível de aprovador dentro do limite configurado "
            f"(nivel_maximo={nivel_maximo}). Verifique "
            "`config.MAX_NIVEL_PROCESSAMENTO` e os níveis detectados na "
            "base SAP."
        )

    # As colunas originais podem ter espaços/acentos e não são
    # identificadores Python válidos, o que impediria o uso de
    # `itertuples` (muito mais rápido que `iterrows` para 90 mil+
    # linhas). Por isso, isolamos apenas as colunas necessárias em um
    # DataFrame auxiliar com nomes seguros ("cc", "desc", "cod_0",
    # "nome_0", ...) só para a iteração.
    renomeacao = {mapeamento.coluna_centro_custo: "cc"}
    colunas_necessarias = [mapeamento.coluna_centro_custo]

    if mapeamento.coluna_descricao_centro_custo:
        renomeacao[mapeamento.coluna_descricao_centro_custo] = "desc"
        colunas_necessarias.append(mapeamento.coluna_descricao_centro_custo)

    for i, nivel in enumerate(niveis_ordenados):
        renomeacao[nivel.coluna_nome] = f"nome_{i}"
        colunas_necessarias.append(nivel.coluna_nome)
        if nivel.coluna_codigo:
            renomeacao[nivel.coluna_codigo] = f"cod_{i}"
            colunas_necessarias.append(nivel.coluna_codigo)

    df_trabalho = df_sap[colunas_necessarias].rename(columns=renomeacao)

    total_linhas = len(df_trabalho)
    resultados: List[ResultadoLinha] = []
    eventos_auditoria: List[EventoAuditoria] = []

    logger.info(
        "Iniciando processamento de %s linhas da base SAP (níveis: %s)...",
        f"{total_linhas:,}",
        ", ".join(n.rotulo for n in niveis_ordenados),
    )

    for posicao, linha in enumerate(df_trabalho.itertuples(index=False, name="LinhaSAP"), start=1):
        linha_dict = linha._asdict()

        centro_custo = linha_dict["cc"]
        descricao = linha_dict.get("desc")

        valores_por_nivel = [
            (
                nivel.rotulo,
                linha_dict.get(f"cod_{i}") if nivel.coluna_codigo else None,
                linha_dict[f"nome_{i}"],
            )
            for i, nivel in enumerate(niveis_ordenados)
        ]

        resultado = _processar_linha(
            centro_custo, descricao, valores_por_nivel, resolvedor, eventos_auditoria
        )
        resultados.append(resultado)

        if posicao % intervalo_log == 0 or posicao == total_linhas:
            logger.info(
                "Processados %s/%s (%.1f%%).",
                f"{posicao:,}",
                f"{total_linhas:,}",
                (posicao / total_linhas) * 100 if total_linhas else 100.0,
            )

    df_resultado = pd.DataFrame([r.__dict__ for r in resultados])
    df_auditoria = pd.DataFrame([e.__dict__ for e in eventos_auditoria])

    return df_resultado, df_auditoria
