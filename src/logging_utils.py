"""
Configuração de logging da automação.

Centraliza a criação de um logger que escreve simultaneamente no
console (para acompanhamento em tempo real) e em um arquivo de log
por execução (para auditoria posterior).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from . import config


def configurar_logger(nome: str = "aprovadores", pasta_logs: str | None = None) -> logging.Logger:
    """Cria (ou reutiliza) um logger configurado com saída para console
    e para um arquivo timestampado dentro de `pasta_logs`.
    """

    pasta_logs = pasta_logs or config.PASTA_LOGS
    os.makedirs(pasta_logs, exist_ok=True)

    logger = logging.getLogger(nome)

    # Evita duplicar handlers se a função for chamada mais de uma vez
    # (por exemplo, em testes que importam o módulo várias vezes).
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    formato = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler_console = logging.StreamHandler()
    handler_console.setFormatter(formato)
    logger.addHandler(handler_console)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho_log = os.path.join(pasta_logs, f"execucao_{timestamp}.log")

    handler_arquivo = logging.FileHandler(caminho_log, encoding="utf-8")
    handler_arquivo.setFormatter(formato)
    logger.addHandler(handler_arquivo)

    logger.propagate = False

    return logger
