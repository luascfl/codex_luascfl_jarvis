---
name: gupy-educorp
description: "Use whenever Lucas asks about Gupy EduCorp, API Pública de Trilhas, Niduu APIs, reports, BI, users/groups, or creating/editing pathways through API or admin UI automation."
---

## Origem
Criada a partir dos contextos:

- `/home/lucas/Downloads/gupy_educorp_api/gupy-educorp`
- `/home/lucas/Downloads/gupy_educorp_api`
- `/home/lucas/.omp/agent/managed-skills/gupy-educorp-ui-automation-rules`

# Gupy EduCorp

Use this skill to help with Gupy EduCorp, also documented as Gupy Treinamento, Gupy Educação Corporativa, Niduu and API Pública de Trilhas.

## Core rule

Treat Gupy credentials as secrets. Do not print real tokens, `clientSecret`, `secret`, bearer tokens, CPF lists, employee emails, or bulk employee payloads unless the user explicitly provided the values in the current task and asks to use them. Prefer placeholders such as `CLIENT_ID`, `CLIENT_SECRET`, `ACCESS_TOKEN`, `SECRET_UUID`, `EMPLOYEE_ID` and `PATHWAY_ID`.

## First step

When the user asks what is possible, how to integrate, or how to call the API:

1. Read `references/api-trilhas.md` for the API Pública de Trilhas.
2. If the task involves users or groups outside the trilhas reporting API, read `references/educorp-usuarios-grupos.md`.
3. If the user provided a local "Gupy - API Pública de Trilhas" credential file with `Client ID` and `secret`, treat `secret` as the `clientSecret` for the Trilhas token endpoint, not as the EduCorp users/groups `secret` query parameter. Read only the needed fields and avoid echoing secrets back.
4. Use the official docs links in the reference files when making factual claims.

## API families

There are two different API styles in Gupy EduCorp:

1. **API Pública de Trilhas**
   - Base: `https://api-pathways.niduu.com/v1/public`
   - Auth: `Authorization: Bearer ACCESS_TOKEN`
   - Token endpoint: `POST /api-settings/token` with `clientId` and `clientSecret`
   - Main uses: list/create trilhas, list contents, list participants, inspect employee progress.

2. **EduCorp users and groups integration API**
   - Example bases: `https://auth.api.niduu.com/integrate` and `https://core.api.niduu.com/integrate`
   - Auth: `secret=SECRET_UUID` query parameter
   - Main uses: create/update/list/deactivate users and create/update/list/delete groups.

Do not mix the authentication models. If a call fails with 401/403, check whether the endpoint expects Bearer token or `secret` query parameter.

## Credential interpretation

If a credential file says **Gupy - API Pública de Trilhas**, **Client ID** and **secret**, it is for the API Pública de Trilhas token flow:

```http
POST https://api-pathways.niduu.com/v1/public/api-settings/token
```

Send `Client ID` as `clientId` and `secret` as `clientSecret`. The returned token is then used as `Authorization: Bearer ACCESS_TOKEN`.

Do not use that `secret` as `?secret=...` for `auth.api.niduu.com` or `core.api.niduu.com`. The users/groups API uses a different EduCorp integration secret.

With only the Trilhas `clientId/clientSecret`, focus on trilhas, contents, participants, employees exposed by the Pathways API, progress reporting, and BI exports. Do not promise user/group provisioning unless the user also has the separate EduCorp integration `SECRET_UUID`.


## Common tasks

### Explain what the API can do

Summarize by capability:

- list trilhas, filter by status, tags, groups, dates and names;
- inspect one trilha;
- list contents in a trilha;
- list groups linked to a trilha;
- list participants in a trilha and filter by status;
- list contents published in trilhas;
- inspect a content item and approval score;
- list employees that accessed content;
- list employees and their trilhas;
- inspect one employee's enrollment in one trilha, including content start and finish dates;
- create trilhas in batch, asynchronously, up to 50 per request;
- manage users and groups through the separate EduCorp integration API.

Also state known limits if relevant: the Trilhas API docs do not expose endpoints for editing/deleting trilhas, creating/editing content, enrolling employees directly into trilhas, or linking content/groups to trilhas.

### Generate request examples

Use safe placeholders and include only the minimal fields.

Token example:

```bash
curl --request POST \
  --url 'https://api-pathways.niduu.com/v1/public/api-settings/token' \
  --header 'accept: application/json' \
  --header 'content-type: application/json' \
  --data '{"clientId":"CLIENT_ID","clientSecret":"CLIENT_SECRET"}'
```

List pathways example:

```bash
curl --request GET \
  --url 'https://api-pathways.niduu.com/v1/public/pathways?maxPageSize=100' \
  --header 'accept: application/json' \
  --header 'Authorization: Bearer ACCESS_TOKEN'
```

Employee pathway detail example:

```bash
curl --request GET \
  --url 'https://api-pathways.niduu.com/v1/public/employees/EMPLOYEE_ID/pathways/PATHWAY_ID' \
  --header 'accept: application/json' \
  --header 'Authorization: Bearer ACCESS_TOKEN'
```

User creation example for the separate EduCorp API:

```bash
curl --request POST \
  --url 'https://auth.api.niduu.com/integrate/users?secret=SECRET_UUID' \
  --header 'accept: application/json' \
  --header 'content-type: application/json' \
  --data '[{"email":"pessoa@example.com","name":"Pessoa Exemplo","lang":"pt"}]'
```

## Integration design guidance

For BI and reporting:

- Start from `/pathways` to build the trilha dimension.
- Use `/pathways/{pathwayId}/employees` for participant status by trilha.
- Use `/employees/{employeeId}/pathways/{pathwayId}` only when content-level enrollment detail is needed, because it fans out heavily.
- Use pagination with `maxPageSize=100` where supported and continue with `nextPageToken` until null or absent.
- Store source IDs as numbers: pathway id, employee id, content id and group id.
- Keep CPF and emails protected as personal data.

For provisioning:

- Use the EduCorp users and groups API for users/groups.
- Use the Trilhas batch create endpoint only for creating pathways.
- Do not assume that creating a group assigns it to a trilha. The public docs separate group management from trilha linkage.

## Response style

Answer in Portuguese by default. Be direct. Use short sections with endpoints and practical implications. Cite official docs URLs when reporting capabilities or limits.

## Referências incorporadas

### API Pública de Trilhas

# API Pública de Trilhas, Gupy EduCorp

Fontes oficiais:

- Convenções: https://developers.gupy.io/reference/conven%C3%A7%C3%B5es-1.md
- Criar token: https://developers.gupy.io/reference/apisettingscontroller_createtoken.md
- Listar trilhas: https://developers.gupy.io/reference/pathwayspublicapicontroller_getpathways.md
- Detalhar trilha: https://developers.gupy.io/reference/pathwayspublicapicontroller_getpathwaybyid.md
- Criar trilhas em lote: https://developers.gupy.io/reference/pathwayspublicapicontroller_batchcreatepathways.md
- Conteúdos da trilha: https://developers.gupy.io/reference/pathwayspublicapicontroller_getcontents.md
- Participantes da trilha: https://developers.gupy.io/reference/pathwayspublicapicontroller_getemployees.md
- Grupos da trilha: https://developers.gupy.io/reference/pathwayspublicapicontroller_getgroups.md
- Listar conteúdos: https://developers.gupy.io/reference/contentspublicapicontroller_getcontents.md
- Detalhar conteúdo: https://developers.gupy.io/reference/contentspublicapicontroller_getcontent.md
- Colaboradores que acessaram conteúdo: https://developers.gupy.io/reference/contentspublicapicontroller_getcontentemployees.md
- Listar colaboradores: https://developers.gupy.io/reference/employeespublicapicontroller_getemployees.md
- Trilhas do colaborador: https://developers.gupy.io/reference/employeespublicapicontroller_getpathways.md
- Detalhe de trilha do colaborador: https://developers.gupy.io/reference/employeespublicapicontroller_getpathwaydetail.md
- Grupos do colaborador: https://developers.gupy.io/reference/employeespublicapicontroller_getgroups.md

## Base e autenticação

Base documentada nos endpoints OpenAPI:

```text
https://api-pathways.niduu.com/v1/public
```

A página de convenções também menciona `https://pathways-core.niduu.com/v1/public`, mas os endpoints OpenAPI atuais usam `https://api-pathways.niduu.com`. Prefira a URL dos endpoints OpenAPI, salvo se o usuário tiver instrução interna diferente.

Autenticação:

```http
Authorization: Bearer ACCESS_TOKEN
```

Token:

```http
POST /api-settings/token
Content-Type: application/json

{
  "clientId": "CLIENT_ID",
  "clientSecret": "CLIENT_SECRET"
}
```

Resposta:

```json
{ "token": "..." }
```

## Credenciais locais da tela "Gupy - API Pública de Trilhas"

Quando a tela ou arquivo local mostrar:

- `Client ID`
- `secret`

use esses campos no endpoint `POST /api-settings/token` como:

```json
{
  "clientId": "CLIENT_ID",
  "clientSecret": "SECRET_DA_TELA"
}
```

Nesse contexto, o campo chamado `secret` é o `clientSecret` da API Pública de Trilhas. Ele não é o mesmo `secret` usado como query parameter na API EduCorp de usuários e grupos.

Depois de gerar o token, use o Bearer token para os endpoints desta referência.

## Paginação

Listagens aceitam:

- `maxPageSize`, padrão 10, geralmente até 100;
- `pageToken`, retornado pela página anterior em `nextPageToken`.

Listagens retornam `results`. Itens únicos retornam `result`.

## Endpoints de trilhas

### Listar trilhas

```http
GET /pathways
```

Filtros:

- `maxPageSize`
- `pageToken`
- `groupNames`
- `isEnabled`
- `isRequired`
- `createdAt`, intervalo ISO 8601
- `name`
- `tags`

Campos principais:

- `id`
- `name`
- `isEnabled`
- `isRequired`
- `workload`
- `createdAt`
- `updatedAt`
- `settings.startAt`
- `settings.finishAt`
- `settings.deadline`

### Detalhar trilha

```http
GET /pathways/{pathwayId}
```

Erros documentados: 401 para autenticação inválida, 403 sem permissão para a trilha.

### Conteúdos de uma trilha

```http
GET /pathways/{pathwayId}/contents
```

Retorna conteúdo básico:

- `id`
- `title`
- `type`

Tipos documentados:

- `ARTICLE`
- `OTHER`
- `COURSE`
- `PODCAST`
- `VIDEO`
- `PDF`
- `DOCUMENT`
- `PRESENTATION`
- `SCORM`
- `EXTERNAL_COURSE`

### Participantes de uma trilha

```http
GET /pathways/{pathwayId}/employees
```

Filtros:

- `finishedAt`, intervalo ISO 8601
- `status`: `TODO`, `FINISHED`, `UNFINISHED`, `DOING`

Retorna:

- `id`
- `name`
- `email`
- `cpf`

### Grupos de uma trilha

```http
GET /pathways/{pathwayId}/groups
```

Retorna:

- `id`
- `name`

### Criar trilhas em lote

```http
POST /pathways:batchCreate
```

Criação assíncrona. O body exige:

- `createdByUser`, UID do usuário criador;
- `pathways`, array de 1 a 50 itens.

Campos de cada trilha:

- `name`, obrigatório;
- `tags`, array;
- `isRequired`, boolean;
- `workloadMinutes`, number;
- `showRanking`, boolean;
- `hasReenrollment`, boolean;
- `showCertificate`, boolean;
- `notificationOnActivate.subject/content`;
- `notificationOnFinish.subject/content`.

Resposta esperada: HTTP 202 com `result.acceptedCount`.

## Endpoints de conteúdos

### Listar conteúdos disponibilizados em trilhas

```http
GET /contents
```

Aceita `pathwayId` como filtro.

### Detalhar conteúdo

```http
GET /contents/{contentId}
```

Retorna:

- `id`
- `title`
- `type`
- `approvalScore`

### Colaboradores que acessaram conteúdo

```http
GET /contents/{contentId}/employees
```

Retorna colaboradores e trilhas associadas ao acesso:

- colaborador: `id`, `name`, `email`, `cpf`
- trilha: `id`, `title`, `startDate`, `endDate`, `scoreAvg`

## Endpoints de colaboradores

### Listar colaboradores

```http
GET /employees
```

Retorna:

- `id`
- `name`
- `email`
- `cpf`
- `blocked`

### Trilhas do colaborador

```http
GET /employees/{employeeId}/pathways
```

Retorna trilhas do colaborador no mesmo formato de `/pathways`.

### Detalhe de trilha do colaborador

```http
GET /employees/{employeeId}/pathways/{pathwayId}
```

Retorna a trilha com `enrollment`:

- `enrollment.startedAt`
- `enrollment.finishedAt`
- `enrollment.contents[]`
- conteúdo: `id`, `title`, `type`, `startedAt`, `finishedAt`

### Grupos do colaborador

```http
GET /employees/{employeeId}/groups
```

Retorna grupos com `id` e `name`.

## Limites observados na documentação pública

A documentação pública de Trilhas não mostra endpoints para:

- editar ou excluir trilhas já criadas;
- criar, editar ou excluir conteúdos;
- vincular conteúdo a trilha;
- matricular colaborador diretamente em trilha;
- vincular grupo a trilha.

Se o usuário precisar dessas ações, verifique se há API privada, permissão adicional, operação pela interface administrativa ou solicitação ao suporte Gupy.

### EduCorp, usuários e grupos

# Gupy EduCorp, usuários e grupos

Fontes oficiais:

- Produto Treinamento: https://developers.gupy.io/docs/produto-educa%C3%A7%C3%A3o-corporativa.md
- Autenticação EduCorp: https://developers.gupy.io/docs/autentica%C3%A7%C3%A3o-educorp.md
- Fluxo de usuários: https://developers.gupy.io/docs/fluxo-de-integra%C3%A7%C3%A3o-de-pessoas-usu%C3%A1rias.md
- Fluxo de grupos: https://developers.gupy.io/docs/fluxo-de-integra%C3%A7%C3%A3o-de-grupos.md

## Diferença para a API Pública de Trilhas

A integração de usuários e grupos da Gupy Educação Corporativa usa outro modelo de autenticação: parâmetro `secret` em cada requisição. Esse `secret` é uma chave de API UUID e deve ficar apenas no servidor. A documentação informa que a API não habilita CORS.

Não confundir com a API Pública de Trilhas, que usa Bearer token.

## Usuários

Base observada nos exemplos oficiais:

```text
https://auth.api.niduu.com/integrate
```

### Criar ou atualizar usuários

```http
POST /users?secret=SECRET_UUID
```

Body é um array, com até 100 pessoas por requisição. Campos principais:

- `nin`, CPF para usuários brasileiros;
- `email`;
- `name`, obrigatório;
- `id_number`, RG, só quando `nin` estiver preenchido;
- `lang`, obrigatório, `pt`, `en` ou `es`;
- `birth_date`, `YYYY-MM-DD`;
- `times_allowed`;
- `mobile_internet_allowed`;
- `metadata`;
- `group`, ID do grupo.

Regra importante: enviar `nin` ou `email`, não os dois juntos. Se já houver registro por CPF ou e-mail, o usuário é atualizado.

`birth_date` e `id_number`, depois definidos em usuário ativo, não podem mais ser alterados.

Exemplo seguro:

```bash
curl --request POST \
  --url 'https://auth.api.niduu.com/integrate/users?secret=SECRET_UUID' \
  --header 'accept: application/json' \
  --header 'content-type: application/json' \
  --data '[{"email":"pessoa@example.com","name":"Pessoa Exemplo","lang":"pt"}]'
```

### Listar usuários

```http
GET /users?secret=SECRET_UUID&q=termo
```

O parâmetro `q` pode buscar por nome, CPF ou e-mail.

### Excluir ou desativar usuário

Use o endpoint oficial de excluir usuário. A documentação informa que:

- se o id é de pré-registro, a rota exclui;
- se o usuário já entrou no aplicativo, a rota desativa.

## Grupos

Base observada nos exemplos oficiais:

```text
https://core.api.niduu.com/integrate
```

Grupos servem para separar permissões e acesso a conteúdos/campanhas.

### Criar grupo

```http
POST /groups?secret=SECRET_UUID
```

Campos:

- `name`, obrigatório;
- `description`, opcional.

### Listar grupos

```http
GET /groups?secret=SECRET_UUID&q=termo
```

### Atualizar grupo

```http
PUT /groups/{group_id}/?secret=SECRET_UUID
```

### Excluir grupo

```http
DELETE /groups/{group_id}/?secret=SECRET_UUID
```

A exclusão é permanente. Se a deleção remover colaboradores do grupo, a primeira chamada pode falhar com um código de confirmação. Reenviar a requisição com o header `confirmation-code` recebido.

### Adicionar usuário a grupo

```http
POST /groups/{group_id}/members/?secret=SECRET_UUID
Content-Type: application/json

{"id": USER_ID}
```

### Listar grupos de um usuário

```http
GET /groups_of/{user_id}/?secret=SECRET_UUID
```

### Listar membros de um grupo

```http
GET /groups/{group_id}/members/?secret=SECRET_UUID
```

## Boas práticas

- Use o sistema interno como fonte de verdade para usuários e grupos quando houver integração recorrente.
- Não use RG como matrícula. A própria documentação alerta que `id_number` é usado como RG em fluxos como recuperação de senha.
- Para matrícula, crie campo personalizado na plataforma.
- Faça cargas em lotes de até 100 usuários.
- Separe logs técnicos de payloads com CPF, e-mail e dados pessoais.

## Evals legados incorporados

```json
{
  "skill_name": "gupy-educorp",
  "evals": [
    {
      "id": 1,
      "prompt": "pesquisa o que dá para fazer com a API Pública de Trilhas da Gupy EduCorp e me entrega os endpoints principais com exemplos seguros",
      "expected_output": "Resposta em português com autenticação Bearer, endpoint de token, endpoints de trilhas, conteúdos, colaboradores, grupos, limites documentados e links oficiais.",
      "files": []
    },
    {
      "id": 2,
      "prompt": "quero montar um BI de treinamentos obrigatórios da Gupy, mostrando quem concluiu, quem está fazendo e quem nem começou. quais chamadas eu uso?",
      "expected_output": "Plano de integração usando /pathways, /pathways/{id}/employees, paginação, status TODO/DOING/FINISHED/UNFINISHED, proteção de CPF/e-mail e estratégia para buscar detalhes só quando necessário.",
      "files": []
    },
    {
      "id": 3,
      "prompt": "como faço para subir usuários e grupos na Gupy Educação Corporativa? é o mesmo token das trilhas?",
      "expected_output": "Explicação de que usuários/grupos usam a API EduCorp com secret na query, não Bearer token da API de Trilhas, com endpoints e exemplos seguros.",
      "files": []
    }
  ]
}
```

---

# Criação e automação de trilhas Gupy EduCorp

Use this when a user asks to create, assemble, edit, or validate a Gupy EduCorp/Niduu trail/pathway from local request evidence, emails, spreadsheets, manager instructions, or an already-open admin UI page.

## Constraints

- Treat Gupy credentials, tokens, CPF, employee e-mails, and bulk employee lists as secrets.
- Public Trail API can create only a basic pathway shell with fields like `name`, `tags`, `isRequired`, `workloadMinutes`, certificate/ranking/rematriculation/notification flags. It does not fully assemble content, groups, participants, or all admin settings.
- If `POST https://api-pathways.niduu.com/v1/public/pathways:batchCreate` returns `HTTP 400 Invalid signature`, assume the current Public Trail API credential is not authorized for creation. Use the admin UI workflow or ask for the correct permission/credential.
- For complete trail assembly, content ordering, workload editing, participants, or settings persistence, prefer admin UI automation after login.

## Local request folder workflow

1. Read the request folder files, especially `.eml` threads and attached spreadsheets.
2. Extract:
   - requested trail name;
   - course/content names in the exact requested order;
   - workload/carga horária informada or evidence sufficient to calculate it;
   - required/optional flag;
   - tags/groups/participants if specified;
   - requester and validation evidence.
3. Cross-check course names against `gupy_api_publica_export/contents.csv` when available, but do not rely on it as exhaustive. The UI may contain newer content not present in the stale export.
4. If the user asks for a shell only, try API `batchCreate`; otherwise use the UI.

## Workload rule

- Toda criação ou montagem de trilha deve preencher carga horária no mesmo ciclo.
- Se usar API `pathways:batchCreate`, inclua `workloadMinutes` no payload.
- Se usar UI, abra `2. Configurações` e preencha o campo de carga horária antes de concluir a montagem.
- Preferência de cálculo: valor explícito no pedido; se não houver, soma das durações dos conteúdos confirmados; se a soma não for confiável, pause e peça validação manual.
- Não entregue uma trilha nova sem carga horária, salvo se Lucas pedir explicitamente para deixar sem valor.
- Após editar, verifique persistência por reload ou pela API Pública de Trilhas em `/pathways/{pathwayId}`. A UI mostra `HH:MM`; a API costuma retornar `HH:MM:SS`.

## Browser setup

For authenticated UI automation, use the persistent Chrome CDP profile required by the project/browser rule:

1. Start or reuse Chrome on `127.0.0.1:9222` with persistent profile.
2. Open `https://niduu.com/admin-beta/pathways?company=5859` through `xd://browser` using `app.cdp_url`.
3. If the page shows login, wait for the user to finish login manually, then continue.
4. Close survey/promotional modals if they block the screen.
5. Do not force-kill Chrome. Preserve session storage.

## Canonical automation owner

For Gupy/Niduu browser work, do not recreate browser operations from scratch when the workflow is already managed by the project Python entrypoint.

- Use `gupy_educorp.py` as the single project-level entrypoint for repeatable Gupy operations.
- If a behavior is missing or broken, patch `gupy_educorp.py` first, then rerun it. Do not solve the same operation through a new ad hoc `xd://browser` snippet or a separate JS file.
- Temporary `xd://browser` snippets are acceptable only to inspect DOM state, test a selector, or verify a saved result. Any reusable click, search, deadline, workload, participant, manager, or content logic must be moved back into `gupy_educorp.py`.
- For a one-off snippet that reveals the solution, immediately consolidate the working logic into `gupy_educorp.py` and report the canonical command used.

## Merged UI automation rules

The former `gupy-educorp-ui-automation-rules` skill is merged here. Use this section with the canonical owner rule above.

### Controlled Vue inputs

Gupy admin uses controlled Vue inputs. If `tab.fill` or raw typing fails, set the native input value and dispatch `input` plus `change` events inside `gupy_educorp.py`.
```js
const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
setter.call(input, "Logística de transportes");
input.dispatchEvent(new Event("input", {bubbles: true}));
input.dispatchEvent(new Event("change", {bubbles: true}));
```

### Accordion and course picker reliability

- Open `4. Conteúdo` by targeting `[data-test-id="accordion-item-content"], [data-testid="accordion-item-content"]`, not a broad text match. Broad `4. Conteúdo` text matches can hit a layout wrapper or sidebar item.
- Search course contents with the native setter, wait for result text, click the exact loose-normalized `h4` match, then click the visible `Adicionar` button.
- Confirm course changes with `Conteúdos adicionados: <N>` and `[data-test-id="content-card"] h4` titles.

### Managers and participants caveat

- `7. Gestão da trilha` manager search can match first and last name even when the visible UI shortens the display name.
- `6. Participantes` may show `Pesquisar participantes/grupos`, but some new pathway states search groups only and do not return individual users. In that case, use the authenticated API fallback already discovered for that session rather than claiming UI success.
- Do not claim participants were added unless the modal selected count plus `Incluir` succeed, an authenticated API call verifies them, or the pathway page visibly lists them afterward.

### Evidence

For each pathway automation run, save a JSON result in the relevant request folder, for example:

```text
criar_trilha/gestor <slug>/automacao_trilha_resultado.json
```

Include statuses for course additions, workload, start/end date, required flag, notifications, managers, participants, final content count, and any UI/API fallback limitation.



## Canonical Python browser commands

Use `gupy_educorp.py` instead of a standalone JS helper.

Current browser commands:

```bash
python3 gupy_educorp.py fix-workload-browser
python3 gupy_educorp.py configure-pathway-browser --config caminho/config_trilha.json --pathway-id PATHWAY_ID --cdp http://127.0.0.1:9222
```

`fix-workload-browser` owns the cycle for workload correction from workload diagnostics: open trail, wait for login, sum visible course durations or ask for manual value, open `2. Configurações`, fill `Carga horária`, click outside, and write an `.xlsx` log.

`configure-pathway-browser` owns JSON-driven trail settings currently ported from the old JS flow:

- `contentDeadline.dateRange.start` and `contentDeadline.dateRange.end` into `4. Conteúdo > config > Data de início e fim`;
- `workloadValue` into `2. Configurações > Carga horária`;
- persistent CDP or Playwright profile login handling;
- JSON evidence output with status, title, workload, and date range.

For new reusable Gupy UI behavior, add it as another `gupy_educorp.py` function/subcommand, not as a separate `.js` helper.

## Creating a trail shell in the UI

1. Click `Nova trilha`.
2. Fill `#input-pathway-name` with the trail name.
3. Fill the tag input via keyboard and press `Enter` after each tag, for example `CX`, `LM Conecta`.
4. Open `2. Configurações`.
5. Set required/mandatory options as requested, using labels nearby when available.
6. Fill the workload/carga horária field with the validated duration. Use explicit request value first; otherwise sum confirmed content durations and format as `HH:MM`.
7. Open `4. Conteúdo`.

## Adding course contents reliably

The Gupy picker is a Vue SPA. DOM `.click()` on cards is unreliable, and `h4.textContent` can include descendant card text such as `CURSO •Gupy Educorp1h previewPré-visualizar`.

Reliable method:

1. If a new empty trail has no section yet, click `NOVA SEÇÃO` before trying to add content.
2. Click `ADICIONAR CONTEÚDO`.
3. Fill `[data-test-id="input-search-course"], [data-testid="input-search-course"]`.
4. Use a robust search term:
   - titles with a colon: use the part before `:`;
   - generic or problematic titles: use a distinctive phrase, for example `falar em público`, `Hora de Inovar`, `Feedback 2.0`, `SWOT`;
   - if exact search returns no results, retry with a shorter distinctive term.
5. In `page.evaluate`, find the matching `[data-test-id="course-item"], [data-testid="course-item"]` by loose-normalized `textContent`.
6. Call `item.scrollIntoView({block: 'center', inline: 'center'})` before clicking. Cards below the viewport return positive `getBoundingClientRect().y`, but Puppeteer mouse coordinates are viewport coordinates, so clicking without scrolling silently misses lower results.
7. Get the card rect after scrolling and click with raw mouse coordinates, usually `page.mouse.click(rect.x + 28, rect.y + 28)`.
8. Confirm `[data-testid="btn-add-course"], [data-test-id="btn-add-course"]` is not disabled.
9. Click the add button.
10. Wait 3 to 4 seconds between adds. Large trails can make the tab appear frozen if automated too fast.
11. Continue in small batches when the user is watching the tab.

## Ordering course contents reliably

Course cards can be reordered by dragging the `drag_indicator` handle. This is automatable and persisted after reload.

Rules:

- Use `[data-test-id="content-card"] h4` to extract current order.
- Normalize titles with the same loose normalization used for add-course matching.
- Reorder from top to bottom using the requested course list from the `.eml` or spreadsheet.
- Prefer adjacent upward moves. Dragging across long off-screen distances is brittle; adjacent moves keep source and target visible.
- The working selector for the drag handle is `.card__handle-wrapper`; each content card is `[data-test-id="content-card"]` and has `draggable="true"`.
- Before each drag, call `target.scrollIntoView({block:'center', inline:'center'})`, where target is the card immediately above the source.
- Then get the handle rect and target rect, and use raw mouse coordinates.

## Workload correction on an existing trail

For a command like `edita a trilha de cx`:

1. Identify the intended pathway by current context, local request folder, browser URL, or API data.
2. Open the edit URL, for example `https://niduu.com/admin-beta/pathways/edit/<pathwayId>?company=5859`.
3. Confirm the name input matches the intended trail before editing.
4. Open `4. Conteúdo` and confirm `Conteúdos adicionados: N` plus the `[data-test-id="content-card"] h4` titles.
5. Run the canonical mature JS helper with empty `coursesToAdd` and `desiredOrder` if only workload should be changed.
6. The helper will sum visible content durations and fill `2. Configurações > Carga horária` when `applyDetectedWorkload: true`.
7. Verify persistence by API:

```python
from pathlib import Path
import importlib.util, sys
spec = importlib.util.spec_from_file_location('gupy_educorp', 'gupy_educorp.py')
g = importlib.util.module_from_spec(spec)
sys.modules['gupy_educorp'] = g
spec.loader.exec_module(g)
api = g.PublicApi(g.parse_credentials(Path(g.DEFAULT_CREDENTIALS)))
row = api.get_result('/pathways/PATHWAY_ID')
print({'id': row.get('id'), 'name': row.get('name'), 'workload': row.get('workload'), 'updatedAt': row.get('updatedAt')})
```

Do not print credentials or tokens. Report only `id`, `name`, `workload`, and `updatedAt`.

Observed CX edit example, 2026-07-22:

- `id`: `44899`
- `name`: `Trilha de Desenvolvimento para a Área de CX`
- contents detected: `35`
- detected workload from visible cards: `231:00`
- API verification after save: `workload = 231:00:00`

## Recovery when automation stops

1. Inspect the current page text and all `h4` titles.
2. Read `Conteúdos adicionados: N` to know the last confirmed count.
3. If the picker is open, identify the visible search results and continue from the course currently being searched.
4. If the picker is closed, click `ADICIONAR CONTEÚDO` and continue from the first missing course.
5. Do not assume a course failed just because the card did not visibly get an `active` class. Some selections enable the add button without a visible class. The add button state is the better signal.
6. If the tab appears frozen during bulk add or reorder, inspect current `h4` titles and continue from the last confirmed card/order position.

## Verification

After adding, reordering, or editing workload:

1. Wait a few seconds for auto-save.
2. Reload the edit URL.
3. Open `2. Configurações` and verify the workload/carga horária value persisted, or use the Public Trail API `/pathways/{pathwayId}`.
4. Open `4. Conteúdo`.
5. Verify `Conteúdos adicionados: <expected_count>`.
6. Extract the `[data-test-id="content-card"] h4` titles.
7. Compare the extracted order with the requested course list using loose normalization.
8. Report exact count, workload value, persistence after reload/API, and any title variants, for example `Feedback 2.0 - V.2026` instead of `Feedback 2.0 - V. 2026`.
