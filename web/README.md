# Aplicação Local por Usuário

Cada pessoa executa a aplicação e o motor Python no próprio computador. As planilhas não são transmitidas para hospedagem pública. O servidor escuta somente no endereço local `127.0.0.1`.

Para preparar um pacote sem dados de entrada, sem resultados e sem histórico Git, execute na raiz do projeto:

```powershell
.\preparar_pacote.ps1
```

Isso gera `dist\aprovadores-local.zip`. Antes de enviar, a pessoa responsável deve verificar que o canal de distribuição é aprovado pela empresa. Não use o repositório Git como método de instalação para colegas: o histórico antigo não faz parte do ZIP, mas ainda existe no remoto.

O arquivo `dist\aprovadores-local.zip` pode ser distribuído apenas por um canal aprovado pela empresa. Cada usuário extrai o pacote e executa `abrir_aplicacao.ps1`. Na primeira execução, o script cria `.venv` na pasta do usuário e instala `requirements.txt`; isso requer Python 3 e acesso ao repositório de pacotes aprovado pela empresa. Execuções seguintes reutilizam o ambiente. Fechar a janela PowerShell encerra o servidor.

Se a política do Windows bloquear scripts, ou Python/pip não estiverem disponíveis, solicite à TI um método aprovado de disponibilização. Não altere políticas nem tente contorná-las.

O empacotador inclui somente `src`, `web`, `requirements.txt`, o inicializador e as instruções. Ele não inclui `.git`, planilhas, logs ou os resultados produzidos. Mesmo assim, confira o conteúdo do ZIP antes de compartilhá-lo.

## Hospedagem Pública

Não publique esta aplicação nem envie planilhas SAP/RH para Vercel, Render ou outro provedor sem autorização explícita da empresa. O Vercel Hobby também limita execução e tamanho de requisição abaixo do necessário para os ciclos reais. O arquivo `render.yaml` é apenas uma configuração histórica de teste e não faz parte do fluxo local recomendado.
