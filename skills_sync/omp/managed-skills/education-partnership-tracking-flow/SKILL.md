---
name: education-partnership-tracking-flow
description: "Use para mapear, atualizar planilhas e gerar rascunhos .eml de parcerias educacionais corporativas para LM/VWFS, preservando status, threads e fluxo de resposta."
---

## Origem
Criada a partir do contexto: `/home/lucas/DHO SharePoint/DHO/PARCERIAS INSTITUIÇÕES DE ENSINO`

## Quando usar
Use esta skill quando Lucas estiver trabalhando no fluxo de parcerias educacionais corporativas da LM Mobilidade e/ou VWFS, especialmente quando houver:

- planilhas `Mapeamento instituições de ensino.xlsx` ou `Mapeamento instituições de ensino Salvador.xlsx`
- pasta `1707/` com `.eml`, `.docx`, `.pdf` e subpasta `Respostas/`
- atualização de status de instituições
- geração, validação ou limpeza de rascunhos `.eml`
- dúvidas sobre quem respondeu, quem só recebeu o e-mail, e quais conversas Lucas consegue responder no Outlook

## Arquivos e pastas principais

- Projeto base: `/home/lucas/DHO SharePoint/DHO/PARCERIAS INSTITUIÇÕES DE ENSINO`
- Workbook principal: `Mapeamento instituições de ensino.xlsx`
- Workbook Salvador original/enriquecido: `Mapeamento instituições de ensino Salvador.xlsx`
- Pasta de evidências e e-mails: `1707/`
- Pasta de rascunhos: `1707/Respostas/`

Abas recorrentes no workbook principal:

- `IES SALVADOR - LM`
- `IES SÃO PAULO - VWFS E LM`
- `CURSOS IDIOMAS E PROFISSIONAIS`
- `PERGUNTAS`

## Regras de interpretação de status

### `RECEBEU`
Neste fluxo, `RECEBEU` não significa que a instituição respondeu. Significa que o e-mail foi enviado/entregue sem retorno de e-mail inválido ou bounce.

Nunca trate `RECEBEU` como resposta recebida sem evidência em `.eml` ou confirmação explícita do Lucas.

Formulação padronizada quando Lucas não está em cópia:

```text
DD/MM Lucas informou que possível envio feito por Letícia sem Lucas em cópia. Status operacional: enviado; sem retorno localizado.
```

Use essa formulação para instituições em que Lucas não acha a conversa no Outlook porque Letícia possivelmente enviou sem copiá-lo.

### E-mail de resposta enviado
Quando Lucas disser que deixou ou enviou as respostas, registre como envio, sem mencionar agendamento, salvo se ele pedir expressamente.

Formulação padronizada:

```text
20/07 Lucas enviou e-mail de resposta para NOME_DA_INSTITUIÇÃO.
```

Exemplos:

```text
20/07 Lucas enviou e-mail de resposta para ESPM.
20/07 Lucas enviou e-mail de resposta para Conquer, usando a thread "Como a Conquer pode apoiar os desafios da Banco Volkswagen".
20/07 Lucas enviou e-mail de resposta para Cogna, Unopar, Anhanguera e Unime. Reunião marcada para terça-feira, 21/07/2026, às 11h10, com Cogna Educação para tratar parceria educacional.
```

Evite formulações como `Lucas informou que...` quando o status é ação operacional já concluída. Use `Lucas enviou...`.

## Agrupamento de instituições por grupo educacional

Quando várias marcas forem atendidas pela mesma empresa ou canal corporativo, agrupe em uma linha só, se Lucas pedir.

Exemplo já aplicado:

```text
Cogna: Unopar, Anhanguera e Unime
```

Nesse caso:

- mantenha uma única linha principal
- remova as linhas separadas das marcas agrupadas
- consolide e-mails, telefones, sites, unidades, fontes e status
- ajuste a referência da tabela/autofiltro depois de deletar linhas
- verifique se não restaram as linhas antigas

Exemplo de contatos Cogna usados no fluxo:

- `beneficioempresa@kroton.com.br`
- `erika.b.alves@cogna.com.br`
- `fabiana.carrozza@cogna.com.br`
- `pamella.s@cogna.com.br`
- WhatsApp Cogna Empresas: `(11) 99173-9719`

## Regra para gerar `.eml` de resposta

Gere `.eml` somente quando houver conversa real para responder ou quando Lucas explicitamente pedir rascunho mesmo sem thread.

Critérios para conversa real:

- existe `.eml` da thread na pasta `1707/`
- Lucas está em `To` ou `Cc`, ou o arquivo foi adicionado por Lucas como evidência de thread acessível
- há `Message-ID` para preservar `In-Reply-To` e `References`

Não gere nem mantenha rascunho de resposta para instituições em que:

- Lucas não está em cópia
- não há `.eml` de retorno
- o status era apenas `RECEBEU`
- Lucas disse que não pretende fazer follow-up agora

Quando descobrir que um rascunho foi criado sem thread válida, remova o `.eml` gerado em `1707/Respostas/` e atualize o status da planilha.

## Cabeçalhos obrigatórios de `.eml`

Todo rascunho deve ser parseável e conter:

- `X-Unsent: 1`
- `From`
- `To`
- `Subject`
- `Date`
- `Message-ID`
- `In-Reply-To`, quando houver thread original
- `References`, quando houver thread original
- corpo `text/plain` em UTF-8

Use `Bcc` para contatos externos secundários quando eles pertencem ao mesmo assunto, empresa ou fórum, e a intenção é evitar expor todos os destinatários.

Não use `.eml` como prova de envio. Ele é apenas rascunho para validação/manual sending, salvo se Lucas informar que o e-mail foi enviado no Outlook.

## Outlook Web

Outlook Web não é confiável para abrir `.eml` local como rascunho editável preservando thread.

Fluxo seguro:

1. Buscar a conversa real no Outlook Web pelo e-mail ou assunto.
2. Abrir o thread original.
3. Clicar em responder ou responder a todos.
4. Copiar o texto do `.eml` correspondente.
5. Validar destinatários, cópias e cópia oculta.
6. Enviar ou agendar no Outlook.

Se a conversa não aparece para Lucas, provavelmente ele não está em cópia. Atualize o status como `enviado; sem retorno localizado` e não mantenha rascunho de resposta para aquela instituição.

## Fluxo operacional recomendado

### 1. Inspecionar workbook
Use `openpyxl` para listar abas, cabeçalhos e linhas relevantes. Não suponha que a coluna `STATUS` tem o mesmo nome em todas as abas. Em algumas abas pode haver `RETORNOS`.

### 2. Inspecionar `.eml`
Use `email.parser.BytesParser(policy=policy.default)` para extrair:

- `From`
- `To`
- `Cc`
- `Bcc`
- `Subject`
- `Date`
- `Message-ID`
- `In-Reply-To`
- `References`
- corpo `text/plain` ou texto extraído de HTML

### 3. Classificar instituições
Classifique cada instituição como:

- resposta real recebida e Lucas em cópia
- resposta real recebida por Letícia sem Lucas em cópia
- e-mail enviado/sem bounce, mas sem retorno localizado
- bounce ou e-mail inválido
- proposta/material recebido
- reunião solicitada
- reunião marcada
- e-mail de resposta enviado

### 4. Atualizar planilha
Atualize somente a linha da instituição ou grupo correto. Preserve wrap text e alinhamento superior.

Depois de alterações estruturais, como deletar linhas ou agrupar marcas, ajuste a referência da tabela/autofiltro e verifique a integridade.

### 5. Gerar ou limpar rascunhos
A pasta `1707/Respostas/` deve conter apenas rascunhos úteis e acionáveis por Lucas.

Remova rascunhos quando Lucas disser que não está em cópia ou que não há conversa para responder.

### 6. Verificar antes de responder
Sempre verificar:

- workbook abre com `openpyxl`
- zero erros Excel detectados (`#REF!`, `#DIV/0!`, `#VALUE!`, `#N/A`, `#NAME?`, `#NUM!`, `#NULL!`)
- `.eml` restantes têm cabeçalhos obrigatórios
- quantidade de rascunhos restante bate com a lista informada

## Verificação rápida de Excel

```python
from openpyxl import load_workbook
wb = load_workbook('Mapeamento instituições de ensino.xlsx', data_only=False)
errs = []
for s in wb.sheetnames:
    ws = wb[s]
    for row in ws.iter_rows():
        for c in row:
            if c.value in {'#REF!','#DIV/0!','#VALUE!','#N/A','#NAME?','#NUM!','#NULL!'}:
                errs.append(f'{s}!{c.coordinate}:{c.value}')
print(errs)
```

## Verificação rápida de `.eml`

```python
from pathlib import Path
from email import policy
from email.parser import BytesParser

ps = sorted(Path('1707/Respostas').glob('*.eml'))
errs = []
for p in ps:
    m = BytesParser(policy=policy.default).parsebytes(p.read_bytes())
    body = m.get_body(preferencelist=('plain',))
    miss = [k for k in ['X-Unsent','From','To','Subject','References'] if not m.get(k)]
    if not body or len(body.get_content()) < 200:
        miss.append('body')
    if miss:
        errs.append(f'{p.name}: {miss}')
print({'count': len(ps), 'errors': errs})
```

## Situações aprendidas neste ciclo

- Cogna atende Unopar, Anhanguera e Unime pelo mesmo fluxo corporativo, então faz sentido agrupar em uma linha quando o objetivo é parceria corporativa.
- `RECEBEU` não é resposta. É apenas ausência de bounce.
- FGV e ISE foram corrigidas porque Lucas não recebeu resposta e não estava em cópia.
- Mackenzie, Santa Casa, USCS, Berlitz, Cultura Inglesa, EF e SEBRAE foram tratadas como enviadas por Letícia sem Lucas em cópia, com status `enviado; sem retorno localizado`.
- A Conquer ganhou thread real quando Lucas adicionou `RE_ Como a Conquer pode apoiar os desafios da Banco Volkswagen.eml`; o rascunho deve usar essa thread, não um fallback genérico.
- Para respostas já enviadas em 20/07, registrar como `20/07 Lucas enviou e-mail de resposta para...`, sem mencionar que estava agendado.

## Procedimento técnico geral para gerar `.eml`

Use when the user asks to create `.eml` files for review or sending later, especially to reply inside existing email threads without creating a new conversation.

## Procedure

1. Inspect source `.eml` files with Python's stdlib email parser.
   - Use `email.parser.BytesParser(policy=policy.default)`.
   - Extract at minimum: `From`, `To`, `Cc`, `Subject`, `Date`, `Message-ID`, `In-Reply-To`, `References`.
   - Extract plain text body only if needed to classify the response.

2. Map one draft per response group.
   - If several institutions/contacts belong to the same company, subject, and forum, create one draft and place secondary external recipients in `Bcc`.
   - Keep the primary respondent in `To`.
   - Keep relevant internal stakeholders in `Cc`.
   - Do not create follow-ups for contacts the user explicitly excluded, such as companies with no reply.

3. Preserve threading.
   - Keep the same user-facing subject, including existing `RE:`, `RES:`, `AW:` or `[EXTERN]` where appropriate.
   - Set `In-Reply-To` from the latest relevant source `Message-ID`.
   - Set `References` as existing `References` plus the latest `Message-ID`, de-duplicated.
   - If no direct source exists, use the closest original outgoing thread as a conservative fallback and state that limitation in the final.

4. Mark the file as an unsent draft.
   - Add header `X-Unsent: 1`.
   - Add `From`, `To`, optional `Cc`, optional `Bcc`, `Subject`, `Date`, `Message-ID`.
   - Use `EmailMessage(policy=policy.SMTP)` and `set_content(..., subtype='plain', charset='utf-8')`.

5. Save into the requested output folder.
   - Use stable numbered filenames, for example `01_Cogna_resposta.eml`.
   - Sanitize filenames with Unicode normalization and allow only simple ASCII filename characters.

6. Verify before yielding.
   - Reparse every generated `.eml`.
   - Check count equals expected.
   - Check every draft has `X-Unsent`, `From`, `To`, `Subject`, `References`, and a non-empty plain body.
   - Print or report parse errors. Do not claim success if any draft fails validation.

## Minimal verification snippet

```python
from pathlib import Path
from email import policy
from email.parser import BytesParser

ps = sorted(Path('output-folder').glob('*.eml'))
errs = []
for p in ps:
    m = BytesParser(policy=policy.default).parsebytes(p.read_bytes())
    body = m.get_body(preferencelist=('plain',))
    miss = [k for k in ['X-Unsent', 'From', 'To', 'Subject', 'References'] if not m.get(k)]
    if not body or len(body.get_content()) < 200:
        miss.append('body')
    if miss:
        errs.append(f'{p.name}: {", ".join(miss)}')
print({'count': len(ps), 'errors': errs})
assert not errs
```

## Notes

- `.eml` drafts are for validation and manual sending. They should not be sent by automation unless the user explicitly asks.
- `Bcc` appears in the local draft for validation. It will not be visible to recipients after sending.
- Some clients may not open `X-Unsent: 1` as editable drafts. The file is still structurally valid and can be imported or copied into a composer.
