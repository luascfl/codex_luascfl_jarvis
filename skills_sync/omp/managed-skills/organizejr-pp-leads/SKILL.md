---
name: organizejr-pp-leads
description: "Use esta skill sempre que Lucas Camilo Carvalho, a OrganizeJr, demandas comerciais, planilhas de leads, EJs, empresas juniores, ICPs, abordagem comercial, enriquecimento de contatos ou pp-leads-brasil forem mencionados nesta pasta. Ela orienta como transformar arquivos Excel/texto/docx em pesquisa, enriquecimento, priorização e abordagem de leads para a OrganizeJr, empresa júnior de Psicologia Organizacional da UNEB Salvador."
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/pp-leads-brasil/organizejr-pp-leads`

# OrganizeJr PP Leads

## Objetivo

Use esta skill para operar o `pp-leads-brasil` no contexto comercial da OrganizeJr. O resultado esperado é uma lista de leads qualificados, enriquecidos quando possível, com justificativa de fit e abordagem pronta para Lucas usar.

## Aprendizados transferidos do projeto Farmácia Jr.

Use esta seção como o consenso do que aprendemos no workspace `tmp_farmaciajr` e deve ser levado para o projeto `pp-leads-brasil`. A intenção não é generalizar demais: é melhorar o caso de uso OrganizeJr com o fluxo que funcionou neste lead real.

### O que funcionou no lead Farmácia Jr.

- Tratar o lead como **EJ para EJ**, não como mercado aberto. A comparação de preço precisa separar `mercado geral`, `OrganizeJr para mercado` e `OrganizeJr para EJ`.
- Pesquisar a EJ antes de fechar proposta. No caso Farmácia Jr., a pesquisa pública ajudou a calibrar tom, serviços, histórico, liderança, impacto institucional e fontes.
- Distinguir evidência pública de inferência comercial. Exemplo: havia nomes públicos de lideranças, mas não havia fonte ligando um líder específico a um resultado específico. A proposta registrou isso sem inventar causalidade.
- Transformar transcrição e ata em diagnóstico comercial: dor principal, impactos, áreas afetadas, nível de urgência, objeções, próximos passos e perguntas de fechamento.
- Montar proposta em camadas: recomendação principal, expansão possível, pacotes, projetos isolados, economia de pacote, objeção de orçamento, fontes e roteiro de reunião.
- Usar tabela real quando o destino for Google Docs. Texto com `|` não vira tabela; quando precisar de tabela no Doc, use a API do Google Docs com `insertTable` e `tabId`.
- Separar preço preliminar de proposta fechada. No caso Farmácia Jr., os valores foram mantidos como faixa de referência até confirmar participantes, profundidade do escopo, grupo decisor e teto de orçamento.

### Como isso muda o uso do pp-leads-brasil

- `pp-leads-brasil` continua sendo o motor de dados: busca, CNPJ, enriquecimento, fontes, contatos e links.
- O enrichment local passa a ter duas superfícies complementares: (1) arquivos locais clássicos como XLSX/PDF/CSV/Markdown e outros artefatos locais; (2) sessões do Perplexity exportadas em Markdown e salvas no caminho do lead ou do ICP correto, com a origem explícita no nome do arquivo.
- O caso de uso OrganizeJr passa a ser também motor de **diagnóstico e proposta**, não só lista de prospecção.
- Para cada lead A ou B, a saída desejada deve poder virar:
  1. tabela de prospecção;
  2. resumo diagnóstico;
  3. proposta ou guia de proposta;
  4. roteiro de reunião;
  5. linha pronta para CRM Ploomes.

### Fluxo mínimo transferido

```text
demanda ou lead -> fonte local/pp-leads -> pesquisa pública -> score ICP -> diagnóstico -> proposta -> roteiro -> Ploomes
```

Não mande para o Ploomes apenas nome e contato. Mande também origem, evidência, hipótese de dor, oferta sugerida, próxima ação, status e link do artefato quando houver.

## Contexto obrigatório

Antes de ranquear ou abordar leads, leia:

1. `organizejr-pp-leads/organizejr-commercial-context.md`
2. `organizejr-pp-leads/Pirâmide de captação e ICPs da OrganizeJr.docx`
3. `organizejr-pp-leads/Relatório Portal BJ EJs 2025 0101.xlsx`, quando a demanda envolver EJs
4. Arquivos de demanda citados pelo usuário ou colocados na pasta, especialmente `.xlsx`, `.csv`, `.docx`, `.txt` e `.md`
5. `leads-brasil-pp-cli/SKILL.md`, se precisar executar ou explicar comandos do pp-leads

Não use memória solta para ICP, nomes, números ou contatos. Reabra a fonte local e cite o arquivo usado.

## Fluxo de trabalho

### 1. Entender a demanda

Extraia dos arquivos ou do pedido:

- segmento desejado: instituições de ensino, EJs/startups, mercado sênior ou outro recorte explícito
- geografia: Salvador, Bahia, Nordeste, Brasil ou lista indicada por Lucas
- quantidade esperada de leads
- objetivo da abordagem: parceria, diagnóstico, capacitação, oficina, indicação, pesquisa, benchmark ou venda direta
- restrições: excluir concorrentes, priorizar contatos institucionais, evitar leads sem CNPJ, usar apenas EJs federadas, usar apenas base local

Se a demanda estiver incompleta, siga o padrão conservador: priorizar Salvador e Bahia, contato institucional, fit alto, baixo risco e próximo passo simples.

### 2. Escolher a fonte certa

- EJs: comece pelo `organizejr-pp-leads/Relatório Portal BJ EJs 2025 0101.xlsx`.
- EJs de comunicação nacional: filtre o relatório BJ por `EMPRESA_JUNIOR` e `CURSOS` usando termos como Comunicação, Jornalismo, Publicidade, Propaganda, Relações Públicas, Audiovisual, Cinema, Rádio, Mídias, Marketing, Design Gráfico e Produção Cultural. Trate como `ICP 2.3 — EJs de Comunicação com Sobrecarga Criativa e Relacional`, hipótese a validar. Não classifique como alta demanda operacional genérica; procure sinais de fadiga criativa, trabalho always-on, aprovação subjetiva, retrabalho, conflito entre criação/atendimento/estratégia, onboarding frágil, insegurança de feedback, exposição em redes, crise/moderação e perda de padrão criativo por troca de gestão. Use Acesso Comunicação Jr. como case candidato e ESPM Jr. como benchmark, nunca como prova fechada de dor sem validação comercial.
- Empresas e contabilidades: use `pp-leads-brasil` para buscar por nome, CNPJ ou CNAE.
- Escolas, cursinhos e instituições de capacitação: use demanda local quando existir; complemente com `pp-leads-brasil` por nome/CNAE e busca web apenas para validar informação pública.
- Quando faltarem sinais públicos de presença social, consistência de marca ou links ativos, complemente com `scrape-creators-pp-cli`, principalmente para Instagram, LinkedIn, TikTok e YouTube.
- Quando já existir uma pesquisa útil sobre o lead no Perplexity, exporte a sessão em Markdown e trate esse arquivo como enrichment local, com o mesmo peso operacional de uma nota/pesquisa salva na pasta.
- O arquivo do lead deve explicitar a origem no nome, por exemplo `engetop.perplexity-search.md`, e ficar dentro da pasta do lead ou do ICP correspondente, não numa pasta separada só para Perplexity.
- Outras EJs de Psicologia: classifique como benchmark, parceria ou inteligência competitiva, não como lead de venda direta por padrão.

### 3. Rodar pp-leads com segurança

Primeiro descubra o estado real da CLI:

```bash
leads-brasil-pp-cli doctor --json
leads-brasil-pp-cli agent-context --pretty
```

Use sempre `--agent` nas execuções de dados. Ele força JSON compacto, sem cor e sem interação.

Quando `doctor` retornar `auth: not configured`, diferencie backend local e API externa. Se `base_url` for `localhost`/`127.0.0.1`, use `LEADS_BRASIL_BEARER_AUTH=local-dev-token` para desenvolvimento local, porque o backend local deste projeto não valida token real. Se `base_url` for API externa, rode auth interativo, peça o token no terminal, exporte `LEADS_BRASIL_BEARER_AUTH` para a sessão e ofereça salvar com `leads-brasil-pp-cli auth set-token`. Não use `--dry-run` em entregas operacionais; use `--dry-run` só em diagnóstico explícito.

Se `doctor` retornar `api: unreachable` com `base_url` local, tente iniciar `server_bin` ou `go run ./cmd/server`. Se retornar unreachable com API externa, corrija `base_url` em `~/.config/leads-brasil-pp-cli/config.toml`. O backend local lê `organizejr-pp-leads/icp/ejs-comunicacao/lead-table-2026-06-17-ejs-comunicacao-lucas.csv`; `company` retorna dados locais e tenta anexar Casa dos Dados quando `CASA_DADOS_API_KEY` ou `PP_LEADS_CASA_DADOS_API_KEY` estiver configurada; `enrich` retorna o payload OrganizeJr, dados Casa dos Dados disponíveis e links `mailto:`/`wa.me` quando houver e-mail ou telefone.

Comandos simplificados (Company e Contact):

```bash
# Busca de empresas (Institucional)
leads-brasil-pp-cli company "contabilidade Salvador" --agent
leads-brasil-pp-cli company "6920-6/01" --agent

# Enriquecimento Institucional
leads-brasil-pp-cli company "34.434.241/0001-60" --agent --deliver file:organizejr-pp-leads/icp/ejs-comunicacao/outputs/34-434-241-0001-60.json

# Enriquecimento de Decisores/Pessoas
leads-brasil-pp-cli contact "Nome da EJ ou empresa" --agent
```

Exemplos úteis com `scrape-creators-pp-cli`:

```bash
scrape-creators-pp-cli doctor
scrape-creators-pp-cli instagram list-profile "perfil_da_ej" --agent
scrape-creators-pp-cli linkedin list-company "nome-da-ej" --agent
scrape-creators-pp-cli bio resolve "https://linktr.ee/exemplo" --agent
```

Antes de usar `contact` com fontes externas reais, rode:

```bash
scripts/setup-contact-goat-auth.sh
```

Esse setup cobre:

- `CASA_DADOS_API_KEY`, para Casa dos Dados;
- login do Happenstance via Chrome;
- login do LinkedIn MCP via `uvx linkedin-scraper-mcp@latest --login`;
- `DEEPLINE_API_KEY`, se quiser waterfall de contato;
- configuração opcional de BYOK para Hunter e Apollo.

### 4. Qualificar pelo ICP da OrganizeJr

Use a pontuação de `organizejr-pp-leads/icp/ejs-comunicacao/metodologia-score-leads-organizejr.md` e o resumo de `organizejr-pp-leads/organizejr-commercial-context.md`:

- 30, aderência ao ICP
- 20, evidência de demanda
- 20, acessibilidade
- 15, capacidade de pagar ou trocar valor
- 15, encaixe de abordagem

Classes:

- A: abordar agora, score 75 ou mais
- B: nutrir, score 55 a 74
- C: monitorar, score abaixo de 55
- Benchmark: referência, parceria ou inteligência competitiva

Sempre explique o score em uma frase curta com evidência da fonte.

### 5. Preparar abordagem

Para cada lead A ou B, gere uma abordagem curta com:

1. evidência objetiva, por exemplo cidade, curso, contratos, crescimento, porte, CNPJ, site, dor descrita ou relação com UNIJr-BA
2. hipótese de dor ligada a Psicologia Organizacional, por exemplo engajamento, comunicação, liderança, cultura, gestão de tempo, carreira, permanência ou RH sem estrutura
3. oferta da OrganizeJr, por exemplo diagnóstico, capacitação, oficina, roda de conversa, trilha, piloto ou conversa de 20 minutos
4. próximo passo claro

Tom por camada:

- Base: educativo, institucional e colaborativo.
- Meio: de par para par, prático e ligado à rotina de gestão.
- Topo: consultivo, com prova social e risco baixo.

### 6. Criar diagnóstico e proposta quando o lead avançar

Quando o lead já tiver reunião, transcrição, ata, briefing ou sinais públicos suficientes, gere um artefato de diagnóstico/proposta além da tabela de prospecção.

Estrutura mínima herdada do caso Farmácia Jr.:

- identificação da reunião: data, formato, participantes, origem do lead e canal de entrada;
- dor principal: uma frase clara, sem suavizar demais;
- impactos relatados: sobrecarga, engajamento, liderança, comunicação, tempo, sucessão, conflitos ou outro impacto comprovado;
- área afetada: liderança, RH, treinamento, clima, produtividade ou gestão;
- o que já foi tentado e por que ainda não resolveu;
- nível de urgência e justificativa;
- recomendação principal e recomendação de expansão;
- pacotes ou projetos isolados, com escopo e entrega;
- faixa preliminar de investimento, se houver base;
- objeções prováveis e resposta;
- perguntas que faltam para fechar a proposta;
- fontes usadas e limites da inferência.

Para EJs, inclua explicitamente se a conversa é `EJ para EJ`. Isso muda preço, linguagem, objeção de orçamento e tom da proposta.

### 7. Preparar atualização do Ploomes

Quando a entrega pedir CRM, gere uma linha ou payload compatível com a planilha/script Ploomes existente em `organizejr-pp-leads/ploomes_crm/`.

Campos recomendados para empresa:

- `Razão Social - Empresa`
- `CNPJ - Empresa` ou `CNPJ`
- `Site - Empresa`
- `Segmento de atuação - Empresa`
- `Estado - Empresa`
- `Cidade - Empresa`
- `Origem - Empresa`
- `Marcadores - Empresa`
- `Relação`
- `Observações`

Campos recomendados para pessoa, quando houver contato nominal:

- `Nome - Pessoa`
- `E-mail - Pessoa`
- `Telefones - Pessoa`
- `Cargo - Pessoa`
- `Departamento - Pessoa`
- `Origem - Pessoa`

Observações deve resumir em formato curto:

```text
Fonte:
Evidência:
Hipótese de dor:
Oferta sugerida:
Próxima ação:
Artefatos:
Pendências:
```

Use backlog/pendência em `Observações` quando faltar fonte, evidência mínima ou próximo passo.

Fluxo operacional de atualização direto no Google Sheets:

```bash
python3 organizejr-pp-leads/ploomes_crm/update_ploomes_clientes.py \
  --use-case-config organizejr-pp-leads/icp/ejs-comunicacao \
  --spreadsheet-id 1cMzEfzHgn50QUjgNww8eqJIIgX6F-G8wskI8R1DzrnU \
  ```

O script:

- lê a `lead-table` do caso de uso;
- atualiza ou adiciona linhas por CNPJ, e-mail ou nome+cidade+UF;
- preenche `Observações` com fonte, evidência, hipótese, oferta, próxima ação e pendências;
- preserva colunas de controle como `Status Importação`, `Ploomes Id Empresa`, `Ploomes Id Pessoa` e `Erro Importação`;
- não depende mais da coluna `Enviar ao Ploomes?`.

Fluxo canônico depois da planilha no Google Sheets:

```text
lead-table + diretório do recorte/ICP
→ update_ploomes_clientes.py
→ Google Sheets / planilha operacional
→ ploomes_apps_script.gs
→ sync two way com a API do Ploomes
```

No fluxo canônico atual:
- não existe `.xlsx` local como fonte de verdade operacional;
- a planilha do Google Sheets é a camada operacional;
- o Apps Script da própria planilha deve:
  - importar do Ploomes para preencher/atualizar empresas e pessoas na planilha;
  - enviar da planilha para o Ploomes as mudanças feitas no Google Sheets.

O script `enrich_ploomes_clientes.py` continua útil para escrever enrichment e artefatos na planilha do Google Sheets. O Apps Script da planilha é o responsável por manter sheet e CRM coerentes nos dois sentidos.

Quando houver `use-case-config` e CNPJ, ele pode aproveitar o backend local `/v1/enrich/{cnpj}`. Quando não houver lead table compatível, o fallback passa a ser a própria linha do CRM planilhado, mais os CLIs auxiliares disponíveis.

Para analisar a saúde do CRM direto na planilha operacional e decidir quem precisa de enrichment, use:

```bash
python3 organizejr-pp-leads/ploomes_crm/analisar_saude_crm.py
```

Esse script:

- remove `CPF - Pessoa` e `Data de nascimento - Pessoa`;
- garante `E-mail - Pessoa` e `E-mail - Empresa`;
- escreve `ICP Considerado`, `Score ICP (0-10)`, `Saúde CRM (0-100)`, `Precisa de enrichment?` e `Motivos de enrichment`;
- usa a própria planilha do Google Sheets como base operacional para priorizar enrichment, sem depender obrigatoriamente de lead table na triagem inicial.
## Formato de saída

Entregue uma tabela principal e um plano curto. Se a demanda envolver proposta ou CRM, inclua também artefatos e campos Ploomes.

Colunas mínimas da prospecção:

| lead | camada | ICP | cidade/UF | CNPJ | contato | fonte | evidência | score | classe | oferta sugerida | primeira mensagem | próximo passo | risco/pendência |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

Campos adicionais quando houver diagnóstico/proposta:

| lead | dor principal | impactos | recomendação principal | expansão possível | objeção provável | perguntas em aberto | artefato |
| --- | --- | --- | --- | --- | --- | --- | --- |

| Razão Social - Empresa | CNPJ - Empresa | Site - Empresa | Segmento de atuação - Empresa | Estado - Empresa | Cidade - Empresa | Origem - Empresa | Marcadores - Empresa | Relação | Observações |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

Depois da tabela, inclua:

- filtros usados;
- comandos `pp-leads` executados, quando houver;
- arquivos consultados;
- fontes públicas usadas;
- leads excluídos e motivo, quando relevante;
- pendências, como contato ausente, autenticação ausente, falta de validação manual ou decisão de não enviar ao Ploomes.

Salve artefatos em `organizejr-pp-leads/` no caminho do lead, ICP ou CRM correspondente quando a entrega gerar arquivo reutilizável. Use nomes previsíveis: `lead-research-AAAA-MM-DD.md`, `lead-table-AAAA-MM-DD.csv`, `diagnostico-<lead>.md`, `proposta-<lead>.md`, `roteiro-reuniao-<lead>.md` e `ploomes-import-AAAA-MM-DD.csv`.

## Regras de qualidade

- Não trate a OrganizeJr. como lead de venda.
- Não invente e-mail, telefone, cargo, faturamento, dor ou vínculo.
- Prefira contatos institucionais.
- Não faça disparo em massa. A saída deve apoiar abordagem personalizada.
- Não use dado sensível ou pessoal sem necessidade comercial clara.
- Se o usuário pedir uma lista operacional, entregue arquivo `.csv` ou `.xlsx`; se pedir estratégia, entregue `.md` com tabela e mensagens.
- Se a demanda explícita de Lucas contrariar a pirâmide, explique o tradeoff e siga a demanda explícita.

## Exemplos de acionamento

- "usa o pp-leads para encontrar contabilidades em Salvador para a OrganizeJr"
- "pega essa planilha de demandas e monta leads e abordagem"
- "quero EJs da Bahia com mais chance de comprar capacitação de gestão de tempo"
- "enriquece esses CNPJs e cria mensagem para abordagem"
- "acha escolas para feira de profissões usando a pirâmide da OrganizeJr"
- "transforma a reunião da Farmácia Jr. em diagnóstico, proposta e roteiro de reunião"
- "gera CSV para atualizar o Ploomes com os leads A e B"
- "pesquisa uma EJ antes da proposta e separa evidência pública de hipótese comercial"
