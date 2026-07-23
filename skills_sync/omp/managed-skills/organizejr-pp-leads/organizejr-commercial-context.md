---
type: doc
name: organizejr-commercial-context
description: Contexto comercial da OrganizeJr para usar pp-leads-brasil em prospecção, enriquecimento e abordagem de leads
category: commercial-context
generated: 2026-06-17
status: filled
scaffoldVersion: "2.0.0"
---

# Contexto comercial da OrganizeJr

## Identidade operacional

- Organização: OrganizeJr., empresa júnior de Psicologia Organizacional da UNEB Salvador.
- Responsável principal nesta pasta: Lucas Camilo Carvalho, assessor comercial da OrganizeJr.
- Uso esperado da pasta: receber demandas comerciais em Excel, textos e documentos; transformar essas demandas em busca de leads, enriquecimento de contatos, priorização e material de abordagem.
- Ferramenta principal de enriquecimento: `pp-leads-brasil`, via CLI `leads-brasil-pp-cli` ou MCP equivalente.

## Fontes canônicas locais

1. `organizejr-pp-leads/Pirâmide de captação e ICPs da OrganizeJr.docx`
   - Define a estratégia de captação em três camadas: instituições de ensino e capacitação, EJs/startups e mercado sênior.
   - Responsáveis citados no documento: Elaine Figueredo e Camilo.
2. `organizejr-pp-leads/Relatório Portal BJ EJs 2025 0101.xlsx`
   - Planilha nacional de EJs, aba `Empresas Juniores`.
   - Extração observada em 2026-06-17: 1.478 registros e 90 colunas.
   - Campos úteis: `EMPRESA_JUNIOR`, `E_MAIL`, `CURSOS`, `SITE`, `CNPJ`, `FEDERATION_NAME`, `NUCLEOS`, `ESTADO`, `CIDADE`, `UNIVERSIDADE`, `MEMBROS`, `FATURAMENTO`, `CONTRATOS`, `CLUSTER_2024`, `E_DE_ALTO_CRESCIMENTO`, `FACEBOOK`, `EJS_PELAS_QUAIS_FOI_INDICADA`, `EJS_QUE_INDICOU`, `TAXA_DE_COLABORACAO`.
3. Arquivos de demanda que Lucas adicionar na pasta.
   - Podem ser `.xlsx`, `.csv`, `.docx`, `.txt` ou `.md`.
   - Devem ser lidos antes de escolher filtros, ICP ou abordagem.
4. `scrape-creators-pp-cli`
   - CLI instalada para scraping social complementar.
   - Uso recomendado: validar presença social, bio, links, consistência de marca, frequência de postagem e sinais públicos de operação em Instagram, LinkedIn, TikTok, YouTube e outras plataformas quando o relatório BJ e o site institucional não bastarem.

## Pirâmide de captação

### Base, instituições de ensino e capacitação

- Complexidade comercial: baixa, relacional e educativa.
- Potencial imediato: alto, proposta de valor fácil.
- Fit: escolas inovadoras, cursinhos, colégios e ambientes educacionais com abertura para desenvolvimento humano, orientação de carreira, permanência estudantil e cultura escolar.
- Serviços aderentes: orientação profissional, feira de profissões, workshops de carreira, rodas de conversa, capacitação de professores, engajamento, permanência e diagnóstico de vocação.
- Abordagem: construir credibilidade, parceria institucional e valor educativo antes de vender agressivamente.

### Meio, empresas juniores e startups

- Complexidade comercial: média, exige personalização e leitura de cultura.
- Potencial imediato: médio, interesse precisa ser construído.
- Há três ICPs distintos neste meio da pirâmide:
  - EJs de alta demanda operacional, validadas pelo caso da Projecta: organizações com operação ativa, volume de entregas, pressão por rotina, virada de gestão, comunicação interna, liderança, produtividade e manutenção de entregas.
  - EJs diferentonas, validadas pelo caso da Prospector: organizações de nichos técnicos, cursos pouco tradicionais ou culturas internas muito específicas, onde o valor está em ler contexto, identidade, linguagem e engajamento antes de propor uma solução.
  - EJs de comunicação com sobrecarga criativa e relacional, hipótese a validar na prospecção nacional: EJs de Comunicação Social, Jornalismo, Publicidade e Propaganda, Relações Públicas, Audiovisual, Comunicação Organizacional, Design, Marketing, Produção Cultural e áreas correlatas. A tese é que a dor não é só volume operacional: a entrega depende de criatividade contínua, exposição em mídias sociais, relacionamento com cliente, aprovações subjetivas, adaptação a tendências/plataformas e manutenção de padrão criativo com alta renovação de membros.
- Serviços aderentes para alta demanda operacional: capacitações em engajamento, comunicação e liderança, gestão de tempo, diagnóstico de cultura e oficinas para times em transição de mandato.
- Serviços aderentes para EJs diferentonas: diagnóstico de cultura e engajamento, oficinas de alinhamento interno, comunicação entre diretoria e membros, liderança adaptada ao contexto da EJ e construção de identidade organizacional.
- Serviços aderentes para EJs de comunicação: diagnóstico de clima criativo e comunicação interna; oficinas de briefing, feedback e aprovação; segurança psicológica para times criativos; gestão emocional do trabalho always-on; prevenção de fadiga criativa; liderança de squads de criação/atendimento; clareza de papéis entre estratégia, criação, atendimento e gestão; onboarding de novos membros; rituais de debriefing, passagem de bastão e aprendizagem; acordos de limites com clientes e protocolo de crise/moderação em redes sociais.
- Cases citados: Projecta para alta demanda operacional; Prospector, EJ de geologia do Pará, para EJ diferentona; Zafiro como reforço de demanda por gestão de tempo e produtividade. O ICP de comunicação ainda é hipótese a validar. Acesso Comunicação Jr. é o melhor case candidato para validação inicial porque combina portfólio criativo amplo, gestão de mídias/conteúdo, formação de lideranças, 32 membros, 31 contratos e R$ 68.255,05 de faturamento no relatório BJ 2025. ESPM Jr. entra como benchmark de maturidade, não como primeiro case.

### Topo, mercado sênior

- Complexidade comercial: alta, venda mais longa e maior exigência de confiança.
- Potencial imediato: baixo, maior concorrência e menor intenção explícita de compra.
- Fit: empresas maduras, especialmente escritórios de contabilidade B2B com 15 a 30 colaboradores, carteira recorrente, atuação consultiva e segmentação clara em saúde, educação, tecnologia ou serviços profissionais.
- Tese comercial: começar pelo desenvolvimento interno de liderança, cultura e RH do escritório; evoluir para canal de indicação qualificada para clientes sem RH estruturado.
- Serviços aderentes: diagnóstico de clima e cultura, capacitações de liderança, trilhas de desenvolvimento, feedback, comunicação, gestão de conflitos, saúde mental, PDI, plano piloto e capacitações para pequenas equipes.
- Case citado: Alcance Contabilidade, escritório no Imbuí, cerca de 20 colaboradores, mais de 100 clientes e foco forte em saúde.

## Recortes observados no relatório BJ

- Total nacional observado: 1.478 EJs.
- Bahia: 72 registros com `ESTADO = BA`.
- Salvador: 27 registros com `CIDADE = Salvador`.
- Federação `UNIJr-BA`: 76 registros.
- Cursos com `Psicologia`: 72 registros.
- EJs de comunicação em geral, por busca em `EMPRESA_JUNIOR` e `CURSOS` com termos como Comunicação, Jornalismo, Publicidade, Propaganda, Relações Públicas, Audiovisual, Cinema, Rádio, Mídias, Marketing, Design Gráfico e Produção Cultural: 93 registros nacionais. Estados mais frequentes observados: SP 18, MG 12, RJ 11, DF 7, RS 5, PE 5, SC 4, PR 4, PB 4, CE 3, BA 3 e GO 3.
- UNEB, pelo campo `UNIVERSIDADE DO ESTADO DA BAHIA`: 8 registros.
- OrganizeJr. aparece no relatório com CNPJ `46.450.772/0001-26`, curso `Psicologia`, federação `UNIJr-BA`, cidade `Salvador`, universidade `UNIVERSIDADE DO ESTADO DA BAHIA`, 19 membros, R$ 7.876 de faturamento, 12 contratos e `CLUSTER_2024 = 1`.

## Pesquisa externa para ICP de comunicação

- Sprout Social descreve burnout de social media como exaustão mental, física e emocional causada por estresse de trabalho não gerenciado; o texto cita estratégia, planejamento, resposta a engajamento, mudanças constantes de redes, fadiga por tendências, carga emocional, falta de apoio e necessidade de priorização e recursos como causas relevantes. Fonte: https://sproutsocial.com/insights/battling-social-media-burnout/
- Acesso Comunicação Jr. informa publicamente atuação desde 2001, mais de 600 projetos, foco em vivência empresarial e formação de lideranças, valores de conexão, compromisso com resultado, inconformismo, autenticidade e proatividade, além de serviços de gestão de mídias, produção de conteúdo, branding, copywriting, planejamento de comunicação, mentoria e tráfego pago. Fonte: https://www.acessojr.com.br/
- ESPM Jr. se posiciona como consultoria de Marketing e Comunicação, com clientes grandes e cases de sucesso, o que serve como benchmark de maturidade para o segmento, não como prova de dor da OrganizeJr. Fonte: https://espmjr.com/

## Exemplos de EJs locais prioritárias para relacionamento

Use estes exemplos como ponto de partida, não como lista fechada.

| EJ | E-mail | Cidade | Sinal comercial | Fonte |
| --- | --- | --- | --- | --- |
| Empresa JR. ADM UFBA | marketing@empresajr.org | Salvador | 75 membros, R$ 1.261.408,76, 125 contratos, cluster 5 | Relatório BJ 2025 |
| ADV Junior Consultoria Jurídica | presidencia@advjunior.com | Salvador | 42 membros, R$ 320.003,58, 143 contratos, cluster 4 | Relatório BJ 2025 |
| Projecta - Arquitetura e Urbanismo UFBA | comercial@projectaufba.com | Salvador | 43 membros, R$ 291.166,66, 86 contratos, cluster 5 | Relatório BJ 2025 |
| Primus Consultoria Empresarial Jr | contato@primusconsultoria.com.br | Salvador | 51 membros, R$ 202.645,00, cluster 3 | Relatório BJ 2025 |
| Produtora Júnior | comercial@produtorajunior.com.br | Salvador | 29 membros, R$ 128.938,74, cluster 4 | Relatório BJ 2025 |
| ENGETOP | contato@engetop.org.br | Salvador | 17 membros, R$ 107.000,00, 31 contratos, cluster 3 | Relatório BJ 2025 |
| Alfa Consultoria Jurídica Júnior | administrador@alfaconsultoriajuridicajr.com.br | Salvador | 26 membros, R$ 105.450,00, 48 contratos, cluster 4 | Relatório BJ 2025 |
| Prisma - Empresa Júnior de Engenharia Química da UFBa | gustavo.cerqueira@prismaengenharia.org | Salvador | 34 membros, R$ 85.913,69, cluster 3 | Relatório BJ 2025 |

## Como qualificar leads

### Pontuação recomendada, 0 a 100

- 30 pontos, aderência ao ICP: setor, porte, momento e dor combinam com uma das três camadas.
- 20 pontos, evidência de demanda: crescimento, volume de contratos, membros, virada de gestão, expansão, dor declarada ou demanda recebida por Lucas.
- 20 pontos, acessibilidade: e-mail institucional, site, CNPJ, proximidade geográfica, ponte por federação, núcleo, indicação ou relacionamento prévio.
- 15 pontos, capacidade de pagar ou trocar valor: faturamento, carteira, maturidade organizacional ou potencial de parceria.
- 15 pontos, encaixe de abordagem: existe oferta clara da OrganizeJr com próximo passo simples.

Metodologia detalhada: `organizejr-pp-leads/icp/ejs-comunicacao/metodologia-score-leads-organizejr.md`.

### Classes de saída

- A, abordar agora: score 75 ou mais, dor clara e contato acionável.
- B, nutrir: score 55 a 74, bom fit, mas falta contato, timing ou prova da dor.
- C, monitorar: score abaixo de 55, fraco fit ou baixa capacidade de ação.
- Benchmark: outras EJs de Psicologia ou gestão de pessoas que servem para referência, parceria ou inteligência competitiva, não necessariamente venda direta.

## Como usar pp-leads no fluxo OrganizeJr

1. Verificar a CLI e o contexto runtime.
   - `leads-brasil-pp-cli doctor --json`
   - `leads-brasil-pp-cli agent-context --pretty`
2. Buscar empresas por nome ou filtro quando o lead não vier do relatório BJ.
   - `leads-brasil-pp-cli leads-brasil-platform-search --name "contabilidade Salvador" --agent --select name,cnpj,city,state,status`
   - `leads-brasil-pp-cli leads-brasil-platform-search --cnae "6920-6/01" --agent --select name,cnpj,city,state,status`
3. Consultar empresa por CNPJ quando o CNPJ estiver disponível.
   - `leads-brasil-pp-cli company "34.434.241/0001-60" --agent --select name,cnpj,status,address,contacts,casadosdados,sources`
4. Rodar camadas extras quando o lead justificar aprofundamento.
   - `leads-brasil-pp-cli company-goat "34.434.241/0001-60" --agent`
   - `leads-brasil-pp-cli contact-goat "Nome da EJ ou empresa" --agent`
   - `scrape-creators-pp-cli doctor`
   - `scrape-creators-pp-cli linkedin profile "https://www.linkedin.com/company/exemplo" --agent`
   - `scrape-creators-pp-cli instagram profile "perfil_da_ej" --agent`
5. Enriquecer quando o lead entrar na lista A ou B e houver justificativa comercial.
   - `leads-brasil-pp-cli enrich "34.434.241/0001-60" --agent --deliver file:organizejr-pp-leads/icp/ejs-comunicacao/outputs/34-434-241-0001-60.json`
6. Registrar fonte, comando usado, data e limitações. Nunca inventar contato, cargo, faturamento, dor ou vínculo.

## Aprendizado aplicado do lead Farmácia Jr.

O workspace `tmp_farmaciajr` mostrou que o fluxo comercial da OrganizeJr precisa ir além de lista de leads:

- Para EJ vendendo para EJ, separar preço parceiro/MEJ de preço de mercado aberto.
- Antes de proposta, pesquisar a organização, serviços, histórico, liderança pública, cases e fontes.
- Na proposta, distinguir evidência pública de hipótese comercial. Não atribuir impacto a líderes individuais sem fonte direta.
- Transformar reunião e transcrição em diagnóstico: dor principal, impactos, área afetada, urgência, objeções, pacotes, perguntas em aberto e roteiro de fechamento.
- Quando houver Google Docs, criar tabelas reais via API quando tabela for requisito. Texto com pipes não basta.
- Para Ploomes, registrar origem, evidência, hipótese de dor, oferta sugerida, próxima ação, artefatos e pendências, não apenas nome e contato.

### Handoff atual para Ploomes

Quando a lista já estiver qualificada, o caminho canônico é Google Sheets primeiro:

```bash
python3 organizejr-pp-leads/ploomes_crm/update_ploomes_clientes.py \
  --use-case-config organizejr-pp-leads/icp/ejs-comunicacao \
  --spreadsheet-id 1cMzEfzHgn50QUjgNww8eqJIIgX6F-G8wskI8R1DzrnU
```

Depois disso, o Apps Script da própria planilha faz o loop bidirecional:

1. importa do Ploomes para manter empresas e pessoas refletidas no Google Sheets;
2. envia do Google Sheets para o Ploomes as mudanças operacionais feitas na planilha.

### Enriquecimento de leads já existentes no Ploomes

Para linhas que já estão no CRM e já têm CNPJ, ou mesmo quando o enriquecimento precisar partir do próprio CRM planilhado, rode:

```bash
python3 organizejr-pp-leads/ploomes_crm/enrich_ploomes_clientes.py \
  --spreadsheet-id 1cMzEfzHgn50QUjgNww8eqJIIgX6F-G8wskI8R1DzrnU \
  --yes \
  --json
```

Isso faz o loop operacional canônico:

1. usa a própria linha da planilha como base mínima de enrichment;
2. quando houver `use-case-config` e CNPJ, pode aproveitar o backend local `pp-leads-brasil` em `/v1/enrich/{cnpj}`;
3. quando não houver lead table compatível, faz fallback para enrichment direto a partir do CRM usando os dados da própria planilha e os CLIs auxiliares disponíveis;
4. escreve status, resumo, links e artefato técnico opcional na planilha do Google Sheets;
5. deixa o Apps Script da planilha responsável por refletir isso no Ploomes dentro do sync two way.

### Saúde do CRM e base de enrichment no próprio Google Sheets

O fluxo agora aceita o próprio CRM planilhado como base operacional para priorizar enrichment, sem depender obrigatoriamente de uma lead table para a triagem inicial.

Comando:

```bash
python3 organizejr-pp-leads/ploomes_crm/analisar_saude_crm.py
```

Esse script:

1. lê a aba `Clientes` do Google Sheets;
2. remove `CPF - Pessoa` e `Data de nascimento - Pessoa`;
3. garante `E-mail - Pessoa` e `E-mail - Empresa`;
4. escreve `ICP Considerado`, `Score ICP (0-10)`, `Saúde CRM (0-100)`, `Precisa de enrichment?` e `Motivos de enrichment`;
5. usa a própria planilha do CRM como base para priorizar o próximo ciclo de enrichment.

## Como abordar

Toda abordagem deve ligar uma evidência do lead a uma hipótese de dor e a uma oferta simples da OrganizeJr.

### Estrutura curta

1. Contexto: cite a evidência objetiva que motivou o contato.
2. Hipótese: conecte a evidência a uma dor provável de pessoas, cultura, liderança, comunicação, engajamento ou carreira.
3. Oferta: proponha uma conversa curta, diagnóstico inicial, capacitação ou parceria piloto.
4. Baixa fricção: deixe claro o próximo passo e o tempo pedido.

### Tom por camada

- Base: educativo, institucional e colaborativo. Foque em carreira, desenvolvimento humano e apoio a jovens/professores.
- Meio: direto, de par para par e situacional. Foque em gestão, engajamento, comunicação, liderança e virada de mandato.
- Topo: consultivo, com prova social e risco baixo. Foque em diagnóstico, piloto, liderança e canal de indicação.

## Entregáveis padrão

Para cada demanda, salvar artefatos em `organizejr-pp-leads/` no caminho do lead, ICP ou CRM correspondente quando houver arquivo gerado.

- `lead-research-AAAA-MM-DD.md`: raciocínio, filtros, fontes e ranking.
- `lead-table-AAAA-MM-DD.csv` ou `.xlsx`: tabela operacional para Lucas usar.
- `outreach-plan-AAAA-MM-DD.md`: abordagem por segmento, mensagens e próximos passos.
- `enrichment/`: respostas de `pp-leads` por CNPJ quando aplicável.

## Cuidados

- Não tratar OrganizeJr. como lead de venda.
- Não usar dados pessoais sensíveis. Priorizar contatos institucionais e informações públicas/profissionais.
- Não fazer disparo em massa. O fluxo é qualificação e abordagem personalizada.
- Se a demanda de Lucas conflitar com a pirâmide, registrar o conflito e priorizar a demanda explícita.
