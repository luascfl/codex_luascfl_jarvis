# Setup e Gerenciamento de IA Gratuita no Oh My Pi / Gemini CLI

Este documento centraliza as regras e o mapeamento de contas utilizadas para manter o uso das IAs de desenvolvimento 100% no nível gratuito, sem consumir os créditos de teste do Google Cloud (GCP) e sem gerar cobranças em cartão de crédito.

## 1. Guia Definitivo para Configurar Vertex AI com Créditos Gratuitos

Para utilizar os créditos de avaliação do Google Cloud (US$ 300) com o Gemini CLI / Oh-My-Pi, é necessário seguir uma sequência precisa de configurações. A rota da "API Key" do AI Studio deve ser evitada se o objetivo é usar os créditos.

### Passo 1: Pré-requisitos no Google Cloud Console
*   **Vincular Faturamento:** Associe uma "Conta de Faturamento" (Billing Account) ao seu projeto. Sem isso, o Vertex AI retornará erro `404 Not Found` para todos os modelos.
*   **Ativar APIs:** Certifique-se de que as APIs `Vertex AI` e `Cloud Billing Budget API` estão ativas para o projeto.
*   **Configurar Alertas de Orçamento:** Para evitar cobranças surpresa, crie um "Orçamento" (Budget) de R$ 100,00 com um alerta para 100% do valor.

### Passo 2: Configuração do Ambiente Local (Terminal)
O ambiente local deve ser configurado para usar "Application Default Credentials" (ADC), ignorando completamente as chaves de API.

1.  **Limpeza de Chaves de API:**
    Remova permanentemente as variáveis `GOOGLE_API_KEY` e `GEMINI_API_KEY` do seu `~/.bashrc` e do `~/.omp/agent/.env`.
    Use o seguinte comando para remover automaticamente as linhas relevantes do seu `~/.bashrc`:
    ```bash
    sed -i -e '/export GOOGLE_API_KEY/d' -e '/export GEMINI_API_KEY/d' ~/.bashrc
    ```
    E para o Oh-My-Pi:
    ```bash
    sed -i 's/^GEMINI_API_KEY=/#&/' ~/.omp/agent/.env
    ```

2.  **Configuração do `.bashrc` para Vertex AI:**
    Adicione as seguintes linhas ao seu `~/.bashrc`:
    ```bash
    export GOOGLE_GENAI_USE_ENTERPRISE=True
    export GOOGLE_CLOUD_PROJECT="project-3ffc6284-a7ba-4685-a37"
    export GOOGLE_CLOUD_LOCATION="global"
    ```
    *Execute `source ~/.bashrc` para aplicar.*

3.  **Autenticação via `gcloud`:**
    Faça o login para gerar as credenciais ADC.
    ```bash
    gcloud auth application-default login
    ```

### Passo 3: Habilitação dos Modelos no Vertex AI
Este é o passo mais crítico e a causa principal dos erros `404`.

1.  **Habilitar Canal de Pré-lançamento (Preview):**
    A forma mais garantida é via API. Execute os dois comandos `curl` documentados na seção "Histórico de Erros" (Apêndice) para forçar a ativação do canal "EXPERIMENTAL".

2.  **Habilitar o Modelo no Model Garden:**
    + Acesse o **Model Garden** do seu projeto no Console GCP.
    + Procure pelo modelo desejado (ex: `gemini-1.5-flash`).
    + **Clique em "Abrir no Agent Studio"**. Esta ação funciona como um "enable" implícito, registrando o modelo para uso via API.
    + Aguarde alguns minutos.

3.  **Verificação (Comando Correto):**
    Após os passos acima, verifique quais modelos estão disponíveis para seu projeto. O comando `gcloud ai models list` é insuficiente. O correto, que consulta o catálogo disponível para sua conta de faturamento, é:
    ```bash
    # O --region=us-central1 pode ser omitido para usar o endpoint global.
    # O --billing-project força a listagem do catálogo completo.
    gcloud ai model-garden models list --billing-project=project-3ffc6284-a7ba-4685-a37 --project=project-3ffc6284-a7ba-4685-a37
    ```
    Se o modelo for listado, o Gemini CLI e outros SDKs funcionarão corretamente.

---

## 2. Contas Logadas Atualmente no Oh My Pi (`/usage`)

Abaixo estão listadas todas as contas de IA integradas e ativas no painel de Uso (`/usage`) do Oh My Pi.

### GitHub Copilot
- **Modelo:** Chat & Completions (Mensal)
- **Conta Principal:** `luascfl`
- **Status:** 99.5% Free / Completions 100% Free
- **Reset:** 27 dias e 5 horas.

### Google Gemini CLI
- **Status:** Operando na cota gratuita de 15 requisições por minuto do AI Studio (API Key).
- **Projeto Base:** `probable-life-428216-k8`
- **Modelos mapeados:**
  - `gemini-2.5-flash` (99.8% free)
  - `gemini-2.5-flash-lite` (98.7% free)
  - `gemini-2.5-pro` (100% free)
  - `gemini-3.1-flash-lite` (98.7% free)

### Google Antigravity
- **Sessão atual atrelada a:** `lucascamr107@gmail.com`
- **Pool de Contas (Semanal/Diário):**
  - `lucascamr107@gmail.com`
  - `tifla...`
  - `vpgg...`
  - `comer...`
  - `trate...`
- **Status:** Aproximadamente 95.9% Free na cota diária.
- **Status:** 100% Free na cota diária.

### OpenAI
- **Pool de Contas:** `lucascamr107@gmail.com`, `tifla...`, `vpgg...`, `comer...`, `trate...`
- **Status:** 100% Free na cota diária.

### OpenAI Codex (30 days free)
- **Pool Gigante de Contas (Esgotado - 0% free):**
  - `vpgg...`, `comer...`, `luasc...`, `lucas...`, `lucas...`, `lucas...`, `flair...`, `psico...`, `lucas...`, `tifla...`, `marta...`, `presi...`, `perm-...`, `dread...`, `amilc...`

## 4. Como habilitar Vertex AI (Opção de Créditos GCP)

Se você optar por utilizar o Vertex AI consumindo os créditos gratuitos de avaliação do GCP, siga o procedimento abaixo.

Atenção: Este procedimento altera o status do projeto de "Nível Gratuito de API" para "Pay-as-you-go". O Google consumirá os créditos de avaliação (US$ 300) e, após o término, passará a cobrar por uso.

1. Vincule uma Conta de Faturamento (Billing Account) no Console do Google Cloud ao seu projeto. Sem isso, o Vertex AI retornará erro 404 para todos os modelos.
2. Ative a API "Vertex AI" no console do projeto.
3. Configure a autenticação via Application Default Credentials (ADC):
   a. Instale o gcloud CLI (`sudo apt install google-cloud-cli`).
   b. Execute no terminal: `gcloud auth application-default login`.
   c. As ferramentas (Gemini CLI / Oh-My-Pi) passarão a usar essa autenticação em vez da API Key.
4. **Habilite o Acesso a Modelos "Preview" (Visualização):**
   a. No Console GCP, procure por **"Gemini para Google Cloud"** e vá para a seção **Admin**.
   b. Encontre a opção **"Canais de lançamento do Gemini Code Assist"**.
   c. Selecione a opção **"Visualizar"** (Preview). Isso libera o acesso aos modelos mais recentes (como `gemini-3.1-pro-preview`) para o seu projeto.
   d. Salve a alteração.

## 5. Configurando Alertas de Gastos (Budgets & Alerts)
Para monitorar o uso dos créditos e receber alertas a cada R$ 100 gastos:
1. No Console GCP, pesquise por "Orçamentos e alertas" (Budgets & Alerts).
2. Clique em "Criar orçamento".
3. Selecione o escopo: este projeto.
4. Definir valor: R$ 100,00.
5. Em "Alertas", defina o limite de 100% (o sistema enviará e-mail quando atingir o valor).

## 6. Novo SDK Google GenAI (Recomendado para Vertex AI)
O novo SDK oficial do Google (`google-genai`) substitui abordagens legadas e utiliza o ambiente ADC configurado.

1. Instale o SDK: `pip install --upgrade google-genai`
2. Configure as variáveis de ambiente no seu `.bashrc`:
   ```bash
   export GOOGLE_CLOUD_PROJECT="project-3ffc6284-a7ba-4685-a37"
   export GOOGLE_CLOUD_LOCATION="global"
   export GOOGLE_GENAI_USE_ENTERPRISE=True
   ```
3. Exemplo de uso:
   ```python
   from google import genai
   from google.genai.types import HttpOptions

   client = genai.Client(http_options=HttpOptions(api_version="v1"))
   response = client.models.generate_content(
       model="gemini-2.5-flash",
       contents="Olá, como o sistema de scripts está organizado?",
   )
   print(response.text)
   ```
## Conclusão
O ecossistema local do Oh My Pi, Gemini CLI e Coders Context está perfeitamente amarrado para priorizar o roteamento de chaves gratuitas (destaque para o resgate do projeto `probable-life` da conta `lucascamr107`). Nenhuma alteração no Vertex AI deve ser feita para evitar faturamento surpresa.

## Apêndice: Histórico de Erros e Soluções Detalhadas

Durante a configuração, mapeamos os seguintes erros no Gemini CLI / Oh My Pi:

### Erro 401 UNAUTHENTICATED (Vertex AI)
* **Sintoma:** O terminal acusa que "API keys are not supported by this API. Expected OAuth2 access token".
* **Causa:** Presença de variáveis `GOOGLE_API_KEY` ou `GEMINI_API_KEY` no ambiente (`.bashrc`, `~/.omp/agent/.env`). O SDK do Google prioriza essas chaves, mas o Vertex exige autenticação OAuth (ADC).
* **Solução:** Remover completamente as variáveis de API Key e re-autenticar com `gcloud auth application-default login`.

### Erro 404 NOT_FOUND (Publisher Model was not found)
* **Sintoma:** Ao tentar chamar um modelo, a API retorna que o modelo não foi encontrado. O comando `gcloud ai models list` retorna "Listed 0 items."
* **Causa 1:** O projeto GCP não tem uma Conta de Faturamento (Billing Account) vinculada.
* **Causa 2 (Principal):** O comando `gcloud ai models list` é insuficiente. Para listar o catálogo de modelos disponíveis para seu faturamento (e não apenas os já "importados" para o projeto), é necessário usar a flag `--billing-project`.
* **Solução:**
  1.  Vincule o faturamento.
  2.  Use o comando `gcloud ai model-garden models list --billing-project=SEU_ID_DE_FATURAMENTO` para ver o que está realmente disponível.
  3.  Para habilitar um modelo para a API, acesse o Model Garden no Console GCP e clique em "Abrir no Agent Studio" para o modelo desejado. Isso o registra para uso.

### Erro de "Preview Release Channel"
* **Sintoma:** A API bloqueia o acesso a modelos "preview" (ex: `gemini-3.1-pro-preview`) mencionando que o canal de pré-lançamento está desativado.
* **Causa:** O projeto não está configurado para aceitar recursos "pre-GA". A tentativa de ativar via UI do "Admin do Gemini" pode não se propagar corretamente.
* **Solução (Definitiva):** Usar os comandos `curl` para chamar a `cloudaicompanion.googleapis.com` e forçar a criação e vinculação da configuração do canal "EXPERIMENTAL" para o projeto.