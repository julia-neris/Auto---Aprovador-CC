"""
Matching de nomes entre a base SAP e a base RH.

Este módulo responde a UMA pergunta: "Quem, no RH, é provavelmente
esta pessoa citada no SAP?". Ele NÃO decide se a pessoa é elegível
para ser aprovador (isso é responsabilidade de `business_rules`) nem
em que ordem os candidatos SAP devem ser avaliados (isso é
responsabilidade de `processor`).

Estratégia (da mais para a menos confiável):
    1. Match exato após normalização.
    2. Match por identificador único (quando as duas bases tiverem um
       identificador em comum -- hoje não é o caso, mas a estrutura
       suporta).
    3. Regra determinística: todos os tokens do nome do SAP aparecem,
       como palavras inteiras, no nome do RH (nomes abreviados no SAP
       são um subconjunto do nome completo do RH).
    4. Fuzzy matching, mas apenas sobre um conjunto de candidatos
       pré-filtrado (não as 25 mil pessoas do RH inteiras), com uma
       pontuação combinada (similaridade textual + palavras em comum)
       para evitar que um sobrenome importante seja ofuscado por um
       nome comum com score textual mais alto.

Qualquer ambiguidade (dois candidatos muito próximos, ou o mesmo nome
normalizado pertencendo a duas pessoas diferentes no RH) é sinalizada
explicitamente, nunca resolvida "no chute".
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd
from rapidfuzz import fuzz

from .column_mapping import MapeamentoRH
from .config import CONFIG_MATCHING, Confianca
from .normalization import normalizar_nome, tokenizar_nome, valor_vazio


# ============================================================
# RESULTADO DO MATCHING (auditável)
# ============================================================

@dataclass
class ResultadoMatch:
    nome_sap: str
    nome_sap_normalizado: str
    encontrado: bool
    confianca: str
    metodo: str
    motivo: str

    rh_index: Optional[int] = None
    nome_rh: Optional[str] = None
    cargo_rh: Optional[str] = None
    matricula_rh: Optional[str] = None
    chefia_rh: Optional[str] = None

    score_final: Optional[float] = None
    score_fuzzy: Optional[float] = None
    score_palavras: Optional[float] = None
    palavras_comuns: Tuple[str, ...] = field(default_factory=tuple)

    # Para casos ambíguos: lista de (nome_rh, score) dos candidatos
    # concorrentes, para permitir revisão humana.
    candidatos_alternativos: Tuple[Tuple[str, float], ...] = field(default_factory=tuple)


def _classificar_confianca(score_final: float, proporcao_palavras: float) -> str:
    cfg = CONFIG_MATCHING

    if score_final >= cfg.score_alto and proporcao_palavras >= cfg.proporcao_palavras_alta:
        return Confianca.ALTA

    if score_final >= cfg.score_medio and proporcao_palavras >= cfg.proporcao_palavras_media:
        return Confianca.MEDIA

    if score_final >= cfg.score_minimo:
        return Confianca.BAIXA

    return Confianca.NAO_ENCONTRADO


# ============================================================
# ÍNDICE DO RH (construído uma única vez, reutilizado para as 91 mil
# linhas do SAP -- essencial para performance)
# ============================================================

class IndiceRH:
    """Estruturas de apoio para busca eficiente de pessoas no RH:
    índice exato (O(1)) e índice por token (para pré-filtrar
    candidatos do fuzzy matching sem varrer a base inteira)."""

    def __init__(self, df_rh: pd.DataFrame, mapeamento: MapeamentoRH):
        self.df = df_rh.reset_index(drop=True)
        self.mapeamento = mapeamento

        self._nomes_normalizados: List[str] = [
            normalizar_nome(valor) for valor in self.df[mapeamento.coluna_nome]
        ]

        self._indice_exato: Dict[str, List[int]] = defaultdict(list)
        self._indice_token: Dict[str, List[int]] = defaultdict(list)
        self._tokens_por_indice: List[Tuple[str, ...]] = []

        for i, nome_normalizado in enumerate(self._nomes_normalizados):
            if not nome_normalizado:
                self._tokens_por_indice.append(tuple())
                continue

            self._indice_exato[nome_normalizado].append(i)

            tokens = tuple(tokenizar_nome(nome_normalizado))
            self._tokens_por_indice.append(tokens)

            for token in set(tokens):
                self._indice_token[token].append(i)

        # Cache de resultados por nome normalizado do SAP: a mesma
        # pessoa costuma aparecer como candidata em várias linhas/
        # colunas, então evitamos recalcular o matching repetidamente.
        self._cache: Dict[str, ResultadoMatch] = {}

    # --------------------------------------------------------
    # API pública
    # --------------------------------------------------------

    def buscar(self, nome_sap) -> ResultadoMatch:
        """Ponto de entrada principal: retorna o resultado de matching
        (com cache) para um nome vindo do SAP."""

        if valor_vazio(nome_sap):
            return ResultadoMatch(
                nome_sap=str(nome_sap) if nome_sap is not None else "",
                nome_sap_normalizado="",
                encontrado=False,
                confianca=Confianca.VAZIO,
                metodo="NOME_VAZIO",
                motivo="Candidato vazio na base SAP.",
            )

        nome_sap_str = str(nome_sap).strip()
        nome_normalizado = normalizar_nome(nome_sap_str)

        if nome_normalizado in self._cache:
            cache_hit = self._cache[nome_normalizado]
            # Preserva o texto original exato desta ocorrência, mesmo
            # usando o resultado do cache.
            return _clonar_com_nome_original(cache_hit, nome_sap_str)

        resultado = self._buscar_sem_cache(nome_sap_str, nome_normalizado)
        self._cache[nome_normalizado] = resultado
        return resultado

    # --------------------------------------------------------
    # Implementação interna
    # --------------------------------------------------------

    def _buscar_sem_cache(self, nome_sap: str, nome_normalizado: str) -> ResultadoMatch:
        # ---- Tier 1: match exato -----------------------------------
        indices_exatos = self._indice_exato.get(nome_normalizado, [])

        if len(indices_exatos) == 1:
            return self._montar_resultado_encontrado(
                nome_sap,
                nome_normalizado,
                indice_rh=indices_exatos[0],
                confianca=Confianca.ALTA,
                metodo="EXATO",
                motivo="Nome idêntico ao cadastrado no RH após normalização.",
                score_final=100.0,
                score_fuzzy=100.0,
                score_palavras=100.0,
            )

        if len(indices_exatos) > 1:
            nomes_candidatos = tuple(
                (self.df.iloc[i][self.mapeamento.coluna_nome], 100.0) for i in indices_exatos
            )
            return ResultadoMatch(
                nome_sap=nome_sap,
                nome_sap_normalizado=nome_normalizado,
                encontrado=False,
                confianca=Confianca.AMBIGUA,
                metodo="EXATO_AMBIGUO",
                motivo=(
                    f"O nome normalizado corresponde a {len(indices_exatos)} "
                    f"pessoas diferentes no RH."
                ),
                candidatos_alternativos=nomes_candidatos,
            )

        # ---- Tier 3: subconjunto determinístico de tokens ----------
        tokens_sap = tokenizar_nome(nome_normalizado)

        if len(tokens_sap) >= CONFIG_MATCHING.minimo_tokens_para_fuzzy:
            resultado_subset = self._tentar_subconjunto_deterministico(
                nome_sap, nome_normalizado, tokens_sap
            )
            if resultado_subset is not None:
                return resultado_subset

        # ---- Tier 4: fuzzy matching sobre pool pré-filtrado ---------
        if len(tokens_sap) < CONFIG_MATCHING.minimo_tokens_para_fuzzy:
            return ResultadoMatch(
                nome_sap=nome_sap,
                nome_sap_normalizado=nome_normalizado,
                encontrado=False,
                confianca=Confianca.BAIXA,
                metodo="NOME_CURTO",
                motivo=(
                    "Nome com poucas palavras para permitir matching "
                    "aproximado seguro."
                ),
            )

        return self._fuzzy_matching(nome_sap, nome_normalizado, tokens_sap)

    def _pool_candidatos(self, tokens_sap: List[str]) -> List[int]:
        """Monta o conjunto de índices do RH candidatos a comparar,
        usando os tokens menos frequentes do nome (normalmente
        sobrenomes) para evitar montar pools com milhares de pessoas
        que só compartilham um primeiro nome comum."""

        postings = [
            (token, self._indice_token.get(token, []))
            for token in tokens_sap
        ]

        # Ignora tokens tão frequentes que não ajudam a discriminar
        # (ex.: primeiros nomes muito comuns), mas apenas se sobrar
        # pelo menos um token mais raro para formar o pool.
        limite = CONFIG_MATCHING.frequencia_maxima_token_para_indexacao
        postings_raros = [(t, lst) for t, lst in postings if len(lst) <= limite]

        base = postings_raros if postings_raros else postings

        pool: set = set()
        for _, lista_indices in base:
            pool.update(lista_indices)

        return list(pool)

    def _tentar_subconjunto_deterministico(
        self, nome_sap: str, nome_normalizado: str, tokens_sap: List[str]
    ) -> Optional[ResultadoMatch]:
        conjunto_sap = set(tokens_sap)
        pool = self._pool_candidatos(tokens_sap)

        correspondentes = []
        for i in pool:
            tokens_rh = set(self._tokens_por_indice[i])
            if conjunto_sap.issubset(tokens_rh):
                correspondentes.append(i)

        if len(correspondentes) == 1:
            return self._montar_resultado_encontrado(
                nome_sap,
                nome_normalizado,
                indice_rh=correspondentes[0],
                confianca=Confianca.ALTA,
                metodo="DETERMINISTICO_SUBCONJUNTO",
                motivo=(
                    "Todas as palavras do nome do SAP aparecem no nome "
                    "cadastrado no RH (nome abreviado/subconjunto)."
                ),
                score_final=97.0,
                score_fuzzy=None,
                score_palavras=100.0,
            )

        if len(correspondentes) > 1:
            # Mais de uma pessoa no RH cujo nome contém todas as
            # palavras do SAP: desempata por fuzzy score, mas só
            # decide se houver margem clara de diferença.
            return self._desempatar_por_fuzzy(
                nome_sap, nome_normalizado, correspondentes, metodo_base="DETERMINISTICO_SUBCONJUNTO"
            )

        return None

    def _desempatar_por_fuzzy(
        self, nome_sap: str, nome_normalizado: str, indices: List[int], metodo_base: str
    ) -> ResultadoMatch:
        pontuados = [
            (i, *self._pontuar_candidato(nome_normalizado, i)) for i in indices
        ]
        pontuados.sort(key=lambda item: item[1], reverse=True)

        melhor_indice, melhor_score, melhor_fuzzy, melhor_palavras = pontuados[0]
        segundo_score = pontuados[1][1] if len(pontuados) > 1 else 0.0

        if (melhor_score - segundo_score) < CONFIG_MATCHING.margem_ambiguidade:
            candidatos = tuple(
                (self.df.iloc[i][self.mapeamento.coluna_nome], round(score, 2))
                for i, score, *_ in pontuados[:5]
            )
            return ResultadoMatch(
                nome_sap=nome_sap,
                nome_sap_normalizado=nome_normalizado,
                encontrado=False,
                confianca=Confianca.AMBIGUA,
                metodo=f"{metodo_base}_AMBIGUO",
                motivo=(
                    f"{len(indices)} pessoas no RH são compatíveis com o nome "
                    f"do SAP e os scores estão muito próximos "
                    f"({melhor_score:.1f} vs {segundo_score:.1f})."
                ),
                candidatos_alternativos=candidatos,
            )

        return self._montar_resultado_encontrado(
            nome_sap,
            nome_normalizado,
            indice_rh=melhor_indice,
            confianca=_classificar_confianca(melhor_score, melhor_palavras),
            metodo=f"{metodo_base}_DESEMPATE_FUZZY",
            motivo="Múltiplos candidatos com o mesmo subconjunto de palavras; desempatado por score combinado.",
            score_final=melhor_score,
            score_fuzzy=melhor_fuzzy,
            score_palavras=melhor_palavras,
        )

    def _pontuar_candidato(self, nome_normalizado_sap: str, indice_rh: int) -> Tuple[float, float, float]:
        """Calcula (score_final, score_fuzzy, score_palavras) de um
        candidato do RH em relação ao nome do SAP."""

        nome_normalizado_rh = self._nomes_normalizados[indice_rh]

        score_fuzzy = fuzz.token_sort_ratio(nome_normalizado_sap, nome_normalizado_rh)

        tokens_sap = set(tokenizar_nome(nome_normalizado_sap))
        tokens_rh = set(self._tokens_por_indice[indice_rh])

        if tokens_sap:
            comuns = tokens_sap & tokens_rh
            score_palavras = (len(comuns) / len(tokens_sap)) * 100
        else:
            score_palavras = 0.0

        score_final = (
            score_fuzzy * CONFIG_MATCHING.peso_fuzzy
            + score_palavras * CONFIG_MATCHING.peso_palavras
        )

        return score_final, score_fuzzy, score_palavras

    def _fuzzy_matching(self, nome_sap: str, nome_normalizado: str, tokens_sap: List[str]) -> ResultadoMatch:
        pool = self._pool_candidatos(tokens_sap)

        if not pool:
            return ResultadoMatch(
                nome_sap=nome_sap,
                nome_sap_normalizado=nome_normalizado,
                encontrado=False,
                confianca=Confianca.NAO_ENCONTRADO,
                metodo="FUZZY_SEM_CANDIDATOS",
                motivo="Nenhuma pessoa no RH compartilha alguma palavra do nome.",
            )

        pontuados = [(i, *self._pontuar_candidato(nome_normalizado, i)) for i in pool]
        pontuados.sort(key=lambda item: item[1], reverse=True)

        melhor_indice, melhor_score, melhor_fuzzy, melhor_palavras = pontuados[0]
        segundo_score = pontuados[1][1] if len(pontuados) > 1 else 0.0

        if melhor_score < CONFIG_MATCHING.score_minimo:
            return ResultadoMatch(
                nome_sap=nome_sap,
                nome_sap_normalizado=nome_normalizado,
                encontrado=False,
                confianca=Confianca.NAO_ENCONTRADO,
                metodo="FUZZY_SCORE_BAIXO",
                motivo=f"Melhor score combinado ({melhor_score:.1f}) abaixo do mínimo aceitável.",
                score_final=melhor_score,
                score_fuzzy=melhor_fuzzy,
                score_palavras=melhor_palavras,
            )

        if (melhor_score - segundo_score) < CONFIG_MATCHING.margem_ambiguidade:
            candidatos = tuple(
                (self.df.iloc[i][self.mapeamento.coluna_nome], round(score, 2))
                for i, score, *_ in pontuados[:5]
            )
            return ResultadoMatch(
                nome_sap=nome_sap,
                nome_sap_normalizado=nome_normalizado,
                encontrado=False,
                confianca=Confianca.AMBIGUA,
                metodo="FUZZY_AMBIGUO",
                motivo=(
                    f"Os dois melhores candidatos têm scores muito "
                    f"próximos ({melhor_score:.1f} vs {segundo_score:.1f}); "
                    f"não é seguro escolher automaticamente."
                ),
                score_final=melhor_score,
                score_fuzzy=melhor_fuzzy,
                score_palavras=melhor_palavras,
                candidatos_alternativos=candidatos,
            )

        confianca = _classificar_confianca(melhor_score, melhor_palavras)

        return self._montar_resultado_encontrado(
            nome_sap,
            nome_normalizado,
            indice_rh=melhor_indice,
            confianca=confianca,
            metodo="FUZZY",
            motivo="Melhor candidato aproximado com margem segura sobre o segundo colocado.",
            score_final=melhor_score,
            score_fuzzy=melhor_fuzzy,
            score_palavras=melhor_palavras,
        )

    def _montar_resultado_encontrado(
        self,
        nome_sap: str,
        nome_normalizado: str,
        indice_rh: int,
        confianca: str,
        metodo: str,
        motivo: str,
        score_final: Optional[float],
        score_fuzzy: Optional[float],
        score_palavras: Optional[float],
    ) -> ResultadoMatch:
        linha_rh = self.df.iloc[indice_rh]
        m = self.mapeamento

        tokens_sap = set(tokenizar_nome(nome_normalizado))
        tokens_rh = set(self._tokens_por_indice[indice_rh])
        palavras_comuns = tuple(sorted(tokens_sap & tokens_rh))

        return ResultadoMatch(
            nome_sap=nome_sap,
            nome_sap_normalizado=nome_normalizado,
            encontrado=True,
            confianca=confianca,
            metodo=metodo,
            motivo=motivo,
            rh_index=indice_rh,
            nome_rh=linha_rh[m.coluna_nome],
            cargo_rh=linha_rh[m.coluna_cargo],
            matricula_rh=linha_rh[m.coluna_matricula] if m.coluna_matricula else None,
            chefia_rh=linha_rh[m.coluna_chefia] if m.coluna_chefia else None,
            score_final=score_final,
            score_fuzzy=score_fuzzy,
            score_palavras=score_palavras,
            palavras_comuns=palavras_comuns,
        )


def _clonar_com_nome_original(resultado: ResultadoMatch, nome_original: str) -> ResultadoMatch:
    """Retorna uma cópia do resultado em cache, mas com o texto
    original desta ocorrência específica (o cache é por nome
    normalizado; o texto "cru" pode variar entre linhas)."""

    if resultado.nome_sap == nome_original:
        return resultado

    dados = resultado.__dict__.copy()
    dados["nome_sap"] = nome_original
    return ResultadoMatch(**dados)


def match_e_confianca_aceitavel(resultado: ResultadoMatch) -> bool:
    """Regra central de segurança: um match só pode ser aceito
    automaticamente se for ALTA, ou MÉDIA quando a configuração
    permitir. BAIXA e AMBÍGUA nunca são aceitos automaticamente."""

    if not resultado.encontrado:
        return False

    if resultado.confianca == Confianca.ALTA:
        return True

    if resultado.confianca == Confianca.MEDIA:
        return CONFIG_MATCHING.aceitar_media_automaticamente

    return False
