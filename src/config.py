"""
Configuração central da automação de aprovadores.

Nenhum limiar de matching, palavra-chave de cargo ou caminho de arquivo
deve ser hardcoded em outros módulos. Tudo que for "ajustável por um
analista sem mexer em lógica" deve morar aqui.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


# ============================================================
# CAMINHOS PADRÃO (podem ser sobrescritos via CLI, ver main.py)
# ============================================================

PASTA_DADOS = "dados"
PASTA_SAIDA = "saídas"

ARQUIVO_SAP_PADRAO = os.path.join(PASTA_DADOS, "aprovadores_sap.xlsx")
ARQUIVO_RH_PADRAO = os.path.join(PASTA_DADOS, "rh.xlsx")
ARQUIVO_SAIDA_PADRAO = os.path.join(PASTA_SAIDA, "resultado_aprovadores_final.xlsx")

# Base "de-para" (SharePoint): cadastro curado, mantido manualmente,
# que relaciona o ID SAP de cada possível aprovador ao seu cargo/
# função e gestor direto atuais. É a fonte PRIMÁRIA de cargo -- muito
# mais confiável que qualquer matching por nome, pois a chave (ID SAP)
# é exata. Só recorremos ao RH completo (matching por nome) quando um
# ID SAP não está cadastrado no de-para (ver `resolver.py`).
ARQUIVO_DEPARA_PADRAO = os.path.join(PASTA_DADOS, "de_para_cc_aprovadores.xlsx")

# Planilha anteriormente enviada pela Belvitur, que este processo
# atualiza com o aprovador calculado e a coluna de Ação.
ARQUIVO_BELVITUR_PADRAO = os.path.join(PASTA_DADOS, "belvitur_base_anterior.xlsx")
ARQUIVO_SAIDA_BELVITUR_PADRAO = os.path.join(PASTA_SAIDA, "belvitur_atualizada.xlsx")

PASTA_LOGS = "logs"


# ============================================================
# FILTRO DE VALIDADE (datas de início/fim de vigência do candidato)
# ============================================================

# A planilha SAP traz, para cada candidato, um período de vigência
# (Início/Fim Validade). Em auditoria de dados históricos, encontramos
# candidatos já elegíveis por cargo mas com vigência expirada que
# ainda assim foram usados em produção -- ou seja, esse filtro NÃO é
# aplicado atualmente no processo real. Por segurança, mantemos a
# opção disponível (para quem quiser habilitá-la), mas desligada por
# padrão, para não divergir do comportamento histórico sem uma decisão
# explícita do time de negócio.
USAR_FILTRO_VALIDADE = False


# ============================================================
# COLUNA DE AÇÃO (reconciliação com a planilha da Belvitur)
# ============================================================

class Acao:
    """Valores possíveis da coluna de Ação gerada na reconciliação."""

    MANTER = "MANTER APROVADOR ATUAL"
    SEM_ACAO = MANTER
    ATUALIZAR = "ATUALIZAR APROVADOR CENTRO DE CUSTO"
    INATIVAR = "INATIVAR CENTRO DE CUSTO"
    REVISAR = "REVISAR CENTRO DE CUSTO"


# Texto usado na coluna "Aprovador SAP" quando nenhum candidato válido
# foi encontrado para o Centro de Custo (equivalente, na planilha
# principal, ao status SEM_APROVADOR/CARGO_NAO_ELEGIVEL/etc. do motor
# de processamento).
TEXTO_INATIVAR_APROVADOR = "INATIVAR"


# ============================================================
# NÍVEIS DE CONFIANÇA DE MATCHING
# ============================================================

class Confianca:
    """Níveis de confiança usados para decidir se um match pode ser
    aceito automaticamente ou precisa de revisão humana."""

    ALTA = "ALTA"
    MEDIA = "MEDIA"
    BAIXA = "BAIXA"
    AMBIGUA = "AMBIGUA"
    NAO_ENCONTRADO = "NAO_ENCONTRADO"
    VAZIO = "VAZIO"


# ============================================================
# LIMIARES DE MATCHING (nada de números mágicos no restante do código)
# ============================================================

@dataclass
class ConfiguracaoMatching:
    # Pontuação combinada mínima para considerar um match (abaixo disso
    # o candidato é tratado como NÃO ENCONTRADO / BAIXA).
    score_minimo: float = 78.0

    # A partir deste score combinado o match é considerado MÉDIA.
    score_medio: float = 85.0

    # A partir deste score combinado o match é considerado ALTA
    # (desde que a proporção mínima de palavras em comum também seja
    # atingida, ver `proporcao_palavras_alta`).
    score_alto: float = 93.0

    # Diferença mínima de score entre o 1º e o 2º colocado no fuzzy
    # matching. Candidatos mais próximos que isso são tratados como
    # AMBÍGUOS e não são escolhidos automaticamente.
    margem_ambiguidade: float = 5.0

    # Proporção mínima de palavras (tokens) do nome SAP que precisam
    # aparecer no nome do RH para que o match seja ALTA confiança.
    proporcao_palavras_alta: float = 1.0

    # Proporção mínima de palavras em comum para MÉDIA confiança.
    proporcao_palavras_media: float = 0.5

    # Quantidade mínima de tokens "significativos" (excluindo
    # preposições) que o nome do SAP precisa ter para que o fuzzy
    # matching seja tentado. Nomes com 1 token só (ex.: "MARIA") são
    # tratados com cautela extra.
    minimo_tokens_para_fuzzy: int = 2

    # Peso do score textual (fuzzy) e do score de palavras em comum na
    # pontuação combinada final. A soma deve ser 1.0.
    peso_fuzzy: float = 0.5
    peso_palavras: float = 0.5

    # Se True, matches de confiança MÉDIA podem ser aceitos
    # automaticamente. Se False, MÉDIA também exige revisão manual.
    aceitar_media_automaticamente: bool = True

    # Tokens muito frequentes no RH (ex.: nomes próprios comuns) não são
    # usados para pré-filtrar candidatos ao fuzzy matching, apenas para
    # pontuação. Isso evita montar pools gigantes de candidatos.
    frequencia_maxima_token_para_indexacao: int = 400

    # Palavras ignoradas na tokenização de nomes (preposições comuns).
    palavras_ignoradas_em_nomes: List[str] = field(
        default_factory=lambda: ["DA", "DE", "DO", "DAS", "DOS", "E"]
    )


CONFIG_MATCHING = ConfiguracaoMatching()


# ============================================================
# REGRA DE NEGÓCIO: QUEM PODE SER APROVADOR
# ============================================================

@dataclass
class ConfiguracaoCargos:
    """Padrões (regex, aplicados sobre o cargo já normalizado) que
    classificam alguém como aprovador de alta liderança elegível."""

    # Cada padrão é testado com re.search sobre o cargo normalizado
    # (maiúsculo, sem acento, espaços colapsados). \b garante que
    # estamos comparando palavras inteiras (evita que "DIRETORIA"
    # seja confundido com "DIRETOR").
    padroes_elegiveis: List[str] = field(
        default_factory=lambda: [
            r"\bDIRETOR\b",
            r"\bDIRETORA\b",
            r"\bVICE[\s-]?PRESIDENTE\b",
            r"\bVICE[\s-]?PRESIDENTA\b",
            r"\bVP\b",
            r"\bCEO\b",
            r"\bCHIEF EXECUTIVE OFFICER\b",
        ]
    )

    # Padrões que, mesmo contendo uma palavra-chave acima, indicam que
    # a pessoa NÃO ocupa de fato o cargo de liderança (ex.: cargos de
    # apoio à diretoria). Avaliados ANTES dos padrões elegíveis: se
    # qualquer exceção casar, o cargo é considerado NÃO elegível.
    padroes_excecao: List[str] = field(
        default_factory=lambda: [
            r"\bASSIST\w*\b.*\bDIRE(TOR|TORIA)\b",
            r"\bDIRE(TOR|TORIA)\b.*\bASSIST\w*\b",
            r"\bAUXILIAR\w*\b.*\bDIRE(TOR|TORIA)\b",
            r"\bESTAGI\w*\b.*\bDIRE(TOR|TORIA)\b",
            r"\bSECRETARI\w*\b.*\bDIRE(TOR|TORIA)\b",
            r"\bASSESSOR\w*\b.*\bDIRE(TOR|TORIA)\b",
            r"\bANALISTA\w*\b.*\bDIRE(TOR|TORIA)\b",
        ]
    )


CONFIG_CARGOS = ConfiguracaoCargos()


# ============================================================
# ORDEM HIERÁRQUICA DOS NÍVEIS DE APROVADOR NO SAP
# ============================================================

# A ordem de negócio (soberana, ver regra 11 do escopo) é:
# N1 -> Sub. -> N2 -> N3 -> N4 -> N5 -> N6
# Cada chave é um "rótulo canônico" e o valor é a posição na sequência.
ORDEM_NIVEIS_APROVADOR = {
    "N1": 0,
    "SUB": 1,
    "N2": 2,
    "N3": 3,
    "N4": 4,
    "N5": 5,
    "N6": 6,
}


# ============================================================
# LIMITE DE NÍVEIS PROCESSADOS NA SEQUÊNCIA SAP
# ============================================================

# Regra de negócio confirmada com a área: para evitar retrabalho, o
# aprovador de um Centro de Custo nunca é buscado além do nível N3.
# Ainda que a planilha SAP traga colunas até N6, os níveis acima deste
# limite são ignorados por padrão. Configurável para o caso do
# processo mudar no futuro (ex.: voltar a considerar até N6) --
# basta apontar para outra chave de `ORDEM_NIVEIS_APROVADOR`.
MAX_NIVEL_PROCESSAMENTO = ORDEM_NIVEIS_APROVADOR["N3"]
