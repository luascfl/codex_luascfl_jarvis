# Metodologia de score, EJs de comunicação

Fonte aplicada: `Relatório Portal BJ EJs 2025 0101.xlsx`.

Uso: ranquear EJs de comunicação para a tarefa de Lucas Camilo, `Prospecção, 20 EJs de comunicação por semana`.

Nota: a metodologia geral, com segmentação por ICP e o caso atual de EJs de comunicação, está consolidada em `organizejr-pp-leads/icp/ejs-comunicacao/metodologia-score-leads-organizejr.md`. Este arquivo permanece como registro específico do primeiro ranking de EJs de comunicação.

## O que o score mede

O score é uma triagem inicial de 0 a 100. Ele não prova compra, nem prova dor. Ele prioriza quem vale validar primeiro com abordagem comercial.

A lógica segue o contexto da OrganizeJr:

- 30 pontos, aderência ao ICP;
- 20 pontos, evidência de demanda;
- 20 pontos, acessibilidade;
- 15 pontos, capacidade de pagar ou trocar valor;
- 15 pontos, encaixe de abordagem.

## Filtro de entrada

Uma EJ entrou no universo de comunicação quando `EMPRESA_JUNIOR` ou `CURSOS` continham ao menos um termo:

- Comunicação
- Jornalismo
- Publicidade
- Propaganda
- Relações Públicas
- Audiovisual
- Cinema
- Rádio
- Mídias
- Marketing
- Design Gráfico
- Produção Cultural

Resultado observado: 93 EJs nacionais.

## Fórmula usada no ranking atual

### 1. Aderência ao ICP, até 30 pontos

Base: 20 pontos.

Adicionar 2 pontos por termo encontrado em `EMPRESA_JUNIOR + CURSOS`, com teto de 30:

- comunicação
- jornalismo
- publicidade
- propaganda
- relações públicas
- audiovisual
- marketing
- design
- mídias
- produção cultural

Interpretação: quanto mais explicitamente a EJ cruza comunicação, criação, mídia, marketing e design, maior o fit com o ICP de sobrecarga criativa e relacional.

### 2. Evidência de demanda, até 20 pontos

Soma com teto de 20:

- contratos ÷ 8, até 8 pontos;
- membros ÷ 8, até 5 pontos;
- `CLUSTER_2024`, até 4 pontos;
- 3 pontos se `E_DE_ALTO_CRESCIMENTO = Sim`;
- faturamento ÷ 100.000, até 3 pontos.

Interpretação: contratos e membros sugerem rotina ativa. Cluster, crescimento e faturamento sugerem maturidade e pressão de entrega.

### 3. Acessibilidade, até 20 pontos

Soma com teto de 20:

- e-mail disponível: 8 pontos;
- site disponível: 5 pontos;
- CNPJ disponível: 4 pontos;
- Facebook disponível: 3 pontos.

Interpretação: lead bom sem canal acionável cai no ranking porque Lucas precisa executar prospecção semanal, não só montar benchmark.

### 4. Capacidade de pagar ou trocar valor, até 15 pontos

Soma com teto de 15:

- faturamento ÷ 150.000 × 6, até 6 pontos;
- contratos ÷ 40 × 5, até 5 pontos;
- membros ÷ 30 × 4, até 4 pontos.

Interpretação: não mede só dinheiro. Mede capacidade operacional, massa crítica de membros e volume que justifique capacitação, diagnóstico ou oficina.

### 5. Encaixe de abordagem, até 15 pontos

Base: 8 pontos.

Adicionar 1,5 ponto por termo encontrado em `EMPRESA_JUNIOR + CURSOS`, com teto de 15:

- comunicação
- publicidade
- jornalismo
- marketing
- mídias
- audiovisual
- design

Interpretação: mede se existe uma ponte simples para mensagem comercial sobre fadiga criativa, feedback, aprovação, onboarding, limites com clientes e gestão emocional do trabalho always-on.

## Classes de decisão

- 75 ou mais: A, abordar agora.
- 55 a 74: B, nutrir ou validar depois.
- abaixo de 55: C, monitorar ou usar apenas se houver motivo estratégico externo.
- Benchmark: lead com maturidade alta, mas que serve mais para aprender e comparar do que vender de imediato.

## Exemplos

### Facto Agência de Comunicação, rank 1

- Aderência: 30,0
- Evidência de demanda: 17,5
- Acessibilidade: 20,0
- Capacidade: 14,7
- Encaixe de abordagem: 14,0
- Total: 96,3

Motivo: cursos fortemente ligados à comunicação, 29 membros, 39 contratos, R$ 204.048,00 de faturamento, cluster 4, alto crescimento, e-mail, site, CNPJ e Facebook disponíveis.

### Ginga Design Empresa Júnior, rank 87

- Aderência: 24,0
- Evidência de demanda: 7,4
- Acessibilidade: 4,0
- Capacidade: 3,7
- Encaixe de abordagem: 11,0
- Total: 50,2

Motivo: entra no filtro por Comunicação Social e Design, mas cai no ranking por ter 7 contratos, R$ 4.830,00 de faturamento, cluster 1 e nenhum e-mail, site ou Facebook no relatório. O CNPJ existe, então ainda pode ser enriquecida via pp-leads.

## Como usar na prática

1. Use o ranking para decidir ordem de trabalho, não para descartar definitivamente.
2. Comece pelos A com contato acionável.
3. Use B quando precisar completar a meta semanal ou validar variações do ICP.
4. Use C quando houver motivo estratégico, como proximidade regional, indicação, parceria ou curiosidade forte do Lucas.
5. Rode `pp-leads-brasil` antes de abordar quando houver CNPJ e o lead for A/B ou estratégico.
6. Depois das respostas, atualize manualmente a classe com dor real validada. Dor real vale mais que score de planilha.

## Limitações

- O score usa dados do relatório BJ, que podem estar desatualizados.
- Ausência de e-mail/site no relatório não significa ausência real, só reduz prioridade operacional.
- Faturamento e contratos podem não capturar intensidade criativa, qualidade do time ou dor interna.
- O ICP de comunicação ainda é hipótese. A validação vem das conversas, não do ranking.
