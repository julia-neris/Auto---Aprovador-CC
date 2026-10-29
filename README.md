# Automação de Aprovadores SAP

Automação que, a partir da base extraída do SAP (Centro de Custo +
candidatos a aprovador N1..N6), determina **quem é o primeiro
Diretor/VP/CEO elegível** na sequência hierárquica de cada Centro de
Custo.

Existe um script pronto na raiz do projeto,
[`rodar_processo.ps1`](rodar_processo.ps1), com os caminhos de arquivo
em variáveis no topo. Basta:
1. Abrir o arquivo e ajustar as variáveis `$Sap`, `$Depara` e `$Rh`. 
2. Rodar, dentro da pasta do projeto:
   ```powershell
   .\rodar_processo.ps1
   ```
3. Ao final ele mostra se deu certo e onde estão os Excels gerados
   (por padrão em `dados_saida\`).

Se o PowerShell bloquear a execução de scripts na primeira vez, rode
uma única vez (como administrador):
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```


## Estrutura do projeto

```
novo_aprovadores/
├── main.py                  # atalho: python main.py --sap ... (chama src/main.py)
├── requirements.txt
├── src/
│   ├── main.py               # CLI e orquestração do fluxo completo
│   ├── config.py             # limiares de matching, cargos elegíveis, caminhos padrão
│   ├── column_mapping.py     # detecção flexível de colunas (SAP, de-para, RH)
│   ├── normalization.py      # normalização de nomes (acentos, espaços, maiúsculas...)
│   ├── matching.py           # índice do RH + estratégia de matching de nomes
│   ├── depara.py             # índice do de-para (Tier 0) + atualização via RH/CPF
│   ├── resolver.py           # combina de-para (Tier 0) e RH (Tier 1) numa única busca
│   ├── business_rules.py     # eh_aprovador_valido(cargo) e regras de elegibilidade
│   ├── processor.py          # percorre N1..N3 e decide o primeiro aprovador elegível
│   ├── validators.py         # validação de qualidade das bases antes de processar
│   ├── output.py             # geração do Excel de auditoria
│   ├── belvitur.py           # reconciliação com a planilha
│   └── logging_utils.py      # configuração de log
├── tests/                    # testes automatizados (pytest)
└── dados_saida/              # saída padrão dos Excels gerados (não versionado)
```

Cada módulo tem uma responsabilidade única, seguindo a separação:
**DADOS → MATCHING → REGRA DE NEGÓCIO → DECISÃO → AUDITORIA**. O
matching (`matching.py`/`resolver.py`) só responde "quem
provavelmente é essa pessoa"; quem decide se ela é elegível é
`business_rules.py`; e quem decide qual candidato vence na ordem SAP é
`processor.py`.
