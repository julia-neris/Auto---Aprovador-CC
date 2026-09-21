# Automação de Aprovadores SAP (Belvitur)

Automação que, a partir da base extraída do SAP (Centro de Custo +
candidatos a aprovador N1..N6), determina **quem é o primeiro
Diretor/VP/CEO elegível** na sequência hierárquica de cada Centro de
Custo, e usa esse resultado para atualizar a planilha enviada pela
Belvitur (com as colunas `APROVADOR SAP` e `AÇÃO`).

Este documento explica **como rodar o processo amanhã** (e em todos os
próximos ciclos) e como validar se o resultado está correto antes de
enviar qualquer coisa para a Belvitur.

---

## 1. Visão geral do fluxo de negócio

```
Base SAP (Centro de Custo + candidatos N1..N6)
        │
        ▼
Base "de-para" (SharePoint) ── ID SAP → Cargo / Gestor  (fonte primária)
        │           ▲
        │           │ opcional: --atualizar-depara
        │           │ (atualiza Cargo/Gestor do de-para via CPF)
        │      Base RH completa (fallback por nome + atualização do de-para)
        ▼
Resolução: para cada Centro de Custo, percorre N1 → Sub. → N2 → N3
(nessa ordem, ignorando candidatos vazios) e escolhe o PRIMEIRO
candidato cujo cargo seja Diretor/VP/CEO.
        │
        ▼
Excel de auditoria (aba "Trilha_Auditoria", "Revisao_Manual", "Resumo")
        │
        ▼
(opcional) Planilha da Belvitur enviada agora
        │
        ▼
Reconciliação: adiciona "APROVADOR SAP" e "AÇÃO" (ATUALIZAR / INATIVAR / vazio)
        │
        ▼
Excel final para a Belvitur (abas "Base Atualizada" e "ATUALIZAR")
```

Pontos importantes da regra de negócio (já implementados no código):

- A **ordem do SAP é soberana**: se N1 já é Diretor, ele é escolhido,
  mesmo que N2 seja CEO.
- Candidato vazio é **ignorado**, o processo continua para o próximo
  nível (não para o processamento da linha).
- Só é considerado **elegível** quem tem cargo Diretor, Vice-Presidente/VP
  ou CEO — com tratamento explícito de falsos positivos (ex.:
  "ASSIST. DIRETORIA" não conta como Diretor).
- A busca por candidato para de N1 até N3 por padrão
  (`config.MAX_NIVEL_PROCESSAMENTO`), pois na prática o aprovador
  elegível raramente aparece depois disso.
- O cargo de cada candidato é buscado **primeiro no de-para** (por ID
  SAP, é a fonte mais confiável) e só cai para matching por nome no RH
  completo se o ID SAP não estiver cadastrado no de-para.
- Quando o nome do SAP não bate exatamente com o nome do RH, existe
  uma estratégia de matching com múltiplos sinais (não apenas o maior
  score de fuzzy matching) e níveis de confiança (ALTA/MEDIA/BAIXA/
  AMBIGUA) — casos de baixa confiança ou ambiguidade **não são
  decididos automaticamente**, vão para a aba `Revisao_Manual`.

---

## 2. Como rodar o processo (passo a passo de amanhã)

### 2.1. Pré-requisitos (só na primeira vez, ou se o ambiente for recriado)

```powershell
cd C:\Users\julia.neris\Documents\novo_aprovadores
python -m venv .venv          # se ainda não existir um ambiente virtual
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Se você já tem o ambiente (`.venv` ou `.venv-1`) configurado, só
ative-o e siga direto para o passo 2.2.

### 2.2. Jeito mais fácil: usar o script `rodar_processo.ps1`

Existe um script pronto na raiz do projeto,
[`rodar_processo.ps1`](rodar_processo.ps1), com os caminhos de arquivo
em variáveis no topo. Basta:

1. Abrir o arquivo e ajustar as variáveis `$Sap`, `$Depara`, `$Rh` e
   `$Belvitur` com os caminhos dos arquivos daquele dia (o resto do
   arquivo não precisa ser mexido).
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

### 2.3. Alternativa: rodar o comando manualmente

Comando geral (ajuste os caminhos dos arquivos de entrada conforme os
que você recebeu/gerou naquele dia):

```powershell
python -m src.main `
  --sap "caminho\para\base sap.xlsx" `
  --depara "caminho\para\de para CC - Aprovadores.xlsx" `
  --rh "caminho\para\base rh.xlsx" `
  --atualizar-depara `
  --belvitur "caminho\para\base que a Belvitur mandou agora.xlsx" `
  --saida "dados_saida\auditoria.xlsx" `
  --saida-belvitur "dados_saida\belvitur_atualizada.xlsx"
```

O que cada argumento faz:

| Argumento | Obrigatório? | O que é |
|---|---|---|
| `--sap` | Sim | Planilha extraída do SAP (Centro de Custo + Aprovador N1..N6). |
| `--depara` | Sim | Planilha "de-para" do SharePoint (ID SAP → Cargo/Gestor). |
| `--rh` | Não | Base de RH completa. Necessária apenas se você quiser (a) usar `--atualizar-depara`, ou (b) ter um fallback de busca por nome para IDs SAP que não estão no de-para. |
| `--atualizar-depara` | Não | Antes de processar, atualiza o Cargo/Gestor do de-para a partir do RH completo, casando por CPF. Requer `--rh`. |
| `--belvitur` | Não | Planilha que a Belvitur enviou agora (a que precisa ser atualizada). Se omitido, o processo gera só o Excel de auditoria, sem a etapa da Belvitur. |
| `--saida` | Não (tem padrão) | Caminho do Excel de auditoria a gerar. |
| `--saida-belvitur` | Não (tem padrão) | Caminho do Excel final para a Belvitur (só é gerado se `--belvitur` for informado). |
| `--sheet-sap` / `--sheet-depara` / `--sheet-rh` / `--sheet-belvitur` | Não | Nome ou índice da aba a usar em cada planilha, caso não seja a primeira. |

**Importante:** `--belvitur` deve sempre ser a planilha que a Belvitur
mandou **naquele ciclo** (a versão mais recente deles), nunca a que
vocês devolveram da vez anterior. O script recalcula tudo do zero a
cada execução, então não existe "estado acumulado" entre rodadas —
basta trocar o arquivo de entrada a cada novo envio da Belvitur.

Tempo esperado: com bases do tamanho atual (~91 mil linhas SAP, ~25
mil RH, ~180 mil linhas Belvitur), o processo completo leva
aproximadamente **12 minutos** (a maior parte é leitura/escrita de
Excel, não o processamento em si).

### 2.4. Conferir se rodou sem erros

Ao final, o terminal deve mostrar uma linha como:

```
Concluído em XXX.X segundos.
```

e o comando deve encerrar com código de saída `0`. Se houver um
problema estrutural nos dados (ex.: coluna obrigatória não encontrada,
planilha vazia, etc.), o processo **para imediatamente** com uma
mensagem clara explicando qual coluna era esperada, o que foi
encontrado e o que revisar — ele não continua silenciosamente com
dados incompletos.

---

## 3. Como testar/validar se a ferramenta está funcionando

Existem **três níveis de teste**, do mais rápido ao mais completo.
Recomendo rodar os três nessa ordem antes de confiar no resultado de
um ciclo novo.

### 3.1. Testes automatizados (regras de negócio) — ~5 segundos

Valida que a lógica central (ordem hierárquica, cargos elegíveis,
candidato vazio, matching de nomes, ambiguidade, etc.) continua correta.
Rode sempre que o código for alterado, ou só para ter certeza de que o
ambiente está íntegro:

```powershell
cd C:\Users\julia.neris\Documents\novo_aprovadores
python -m pytest tests\ -v
```

Resultado esperado: `27 passed`. Se algum teste falhar, **não** rode o
processo real antes de investigar — algo na lógica pode ter quebrado.

### 3.2. Conferência manual dos Excels de saída — alguns minutos

Depois de rodar o processo (seção 2), abra os arquivos gerados e
confira:

**No Excel de auditoria (`--saida`):**
- Aba **"Resumo"**: veja os indicadores gerais (total processado,
  quantos tiveram aprovador encontrado, quantos ficaram sem aprovador,
  distribuição por nível SAP e por confiança de match). Compare com o
  que você espera intuitivamente daquele ciclo (ex.: se souber que
  pouca coisa mudou, o número de "sem aprovador" não deveria disparar).
- Aba **"Revisao_Manual"**: são só os casos que a ferramenta **não**
  decidiu sozinha (baixa confiança, ambiguidade, pessoa não encontrada,
  cargo não elegível). Revise linha a linha antes de considerar o
  resultado final — é justamente para isso que essa aba existe.
- Aba **"Trilha_Auditoria"**: para qualquer aprovador escolhido, mostra
  o nome original do SAP, o nome encontrado no RH/de-para, o método de
  matching usado, o score, o nível de confiança e o cargo — use para
  explicar/justificar uma decisão específica se alguém questionar.

**No Excel para a Belvitur (`--saida-belvitur`):**
- Aba **"ATUALIZAR"**: contém só as linhas com ação pendente
  (`ATUALIZAR APROVADOR CENTRO DE CUSTO` ou `INATIVAR CENTRO DE
  CUSTO`). É essa aba que deve receber a revisão final antes do envio.
- Aba **"Base Atualizada"**: todas as linhas originais da Belvitur, na
  mesma ordem, com as colunas novas preenchidas.

### 3.3. Comparação com uma entrega anterior (validação de regressão)

Se você tiver a planilha que foi devolvida à Belvitur em um ciclo
anterior, é possível comparar o resultado novo com o antigo para
confirmar que a ferramenta está sendo consistente (e entender
qualquer divergência antes de mandar). Isso foi feito manualmente
nesta etapa de desenvolvimento; se quiser repetir esse tipo de
comparação no futuro, me avise que eu monto o script.

Sinais de alerta ao comparar dois ciclos:
- Um número de `INATIVAR`/`ATUALIZAR` muito diferente do ciclo
  anterior **sem** uma explicação óbvia (ex.: de-para atualizado com
  muitas mudanças de cargo naquele dia) merece uma segunda checagem
  antes do envio.
- Um aumento repentino de linhas na aba `Revisao_Manual` pode indicar
  problema na base de origem (ex.: coluna de nome mal preenchida) —
  vale abrir a base SAP/de-para e conferir manualmente algumas linhas.

---

## 4. Estrutura do projeto

```
novo_aprovadores/
├── main.py                  # atalho: python main.py --sap ... (chama src/main.py)
├── requirements.txt
├── src/
│   ├── main.py               # CLI e orquestração do fluxo completo
│   ├── config.py             # limiares de matching, cargos elegíveis, caminhos padrão
│   ├── column_mapping.py     # detecção flexível de colunas (SAP, de-para, RH, Belvitur)
│   ├── normalization.py      # normalização de nomes (acentos, espaços, maiúsculas...)
│   ├── matching.py           # índice do RH + estratégia de matching de nomes
│   ├── depara.py             # índice do de-para (Tier 0) + atualização via RH/CPF
│   ├── resolver.py           # combina de-para (Tier 0) e RH (Tier 1) numa única busca
│   ├── business_rules.py     # eh_aprovador_valido(cargo) e regras de elegibilidade
│   ├── processor.py          # percorre N1..N3 e decide o primeiro aprovador elegível
│   ├── validators.py         # validação de qualidade das bases antes de processar
│   ├── output.py             # geração do Excel de auditoria
│   ├── belvitur.py           # reconciliação com a planilha da Belvitur
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

---

## 5. Ajustando parâmetros sem mexer no código

Tudo que for "configurável por um analista" está centralizado em
[`src/config.py`](src/config.py) — nada de números mágicos espalhados
pelo código. Por exemplo:

- `CONFIG_MATCHING`: limiares de score (`MATCH_SCORE_MINIMO`,
  `MATCH_SCORE_ALTO`, `MATCH_SCORE_MEDIO`, `MINIMO_PALAVRAS_COMUNS`) que
  definem os níveis de confiança do matching de nomes.
- `CONFIG_CARGOS`: palavras/expressões que definem quais cargos contam
  como Diretor/VP/CEO, e as exceções que **não** devem contar (falsos
  positivos como "ASSIST. DIRETORIA").
- `MAX_NIVEL_PROCESSAMENTO`: até qual nível (N1..N6) o processo busca
  um aprovador antes de desistir (padrão: N3).
- `USAR_FILTRO_VALIDADE`: liga/desliga o filtro de datas de vigência
  do candidato (desligado por padrão, para manter compatibilidade com
  o comportamento histórico do processo manual).

Se um novo caso de nome de coluna, cargo ou exceção aparecer no
futuro, normalmente basta ajustar esse arquivo — sem tocar na lógica
dos demais módulos.

---

## 6. O que fazer se o processo parar com erro

O sistema foi projetado para **não seguir silenciosamente** quando
algo está estruturalmente errado. Se ele parar, a mensagem de erro
deve dizer:

- qual coluna/arquivo era esperado;
- o que foi encontrado;
- por que não foi possível prosseguir;
- o que revisar.

Erros mais comuns:
- **Arquivo não encontrado**: confira o caminho passado em `--sap`,
  `--depara`, `--rh` ou `--belvitur`.
- **Coluna não identificada com confiança**: a planilha pode ter
  colunas renomeadas/faltando. Abra a planilha, confira os nomes reais
  das colunas e compare com o que a mensagem de erro esperava.
- **Base vazia ou com problema grave de qualidade** (ex.: nenhuma
  linha, todas as colunas de aprovador vazias): revise a exportação de
  origem antes de rodar novamente.
