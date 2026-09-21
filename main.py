"""
Atalho na raiz do projeto para a automação de aprovadores.

Permite executar `python main.py --sap ... --rh ... --saida ...`
diretamente, sem precisar saber que a implementação está organizada
em módulos dentro de `src/`.
"""

import sys

from src.main import executar

if __name__ == "__main__":
    sys.exit(executar())
