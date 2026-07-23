---
name: ai-design-taste
description: "Princípios e templates de prompt para forçar IAs (Canva, v0, etc) a usarem \"Design Taste\" (minimalismo, respiro, hierarquia), evitando designs genéricos ou poluídos."
---

## Origem
Criada a partir do contexto: `Global`

# AI Design Taste

Use this skill whenever you need to prompt an AI (like Canva's Magic Design, v0, Claude, or Codex) to generate layouts, slides, or UI components with high aesthetic quality, avoiding the dense, generic look known as "AI Slop".

## O Problema do "AI Slop"
IAs geradoras de layout tendem a preencher todo o espaço disponível, criar caixas desnecessárias, usar hierarquias tipográficas confusas e poluir a tela. O "Design Taste" força a IA a agir como um Diretor de Arte Sênior.

## Os 4 Princípios de Ouro (Core Principles)
Ao instruir uma IA para criar ou formatar um design, injete as seguintes restrições:

1. **Whitespace (Respiro/Espaço Negativo):** Exija margens generosas (`padding` e `margin` amplos). Os elementos devem "respirar". O espaço vazio é um elemento ativo do design, não um erro.
2. **Hierarquia Tipográfica:** O contraste entre o Título e o Corpo deve ser extremo. Títulos devem ter peso visual (ex: Negrito, tamanho muito maior), enquanto o corpo do texto deve ser fino, limpo e legível. 
3. **Carga Cognitiva (Minimalismo):** Proíba o uso de linhas conectoras, bordas desnecessárias ou fundos com texturas que não agregam informação. A estrutura deve ser invisível, guiada pelo alinhamento.
4. **Alinhamento:** Forçe alinhamentos consistentes (preferencialmente à esquerda para textos longos) para criar uma grade (grid) invisível forte.

## Template de Prompt (Copiar e Colar)
Sempre que o usuário pedir para você gerar um prompt para o Canva IA (ou Vercel v0, etc.), anexe este bloco de regras:

```text
Atue como um Diretor de Arte Sênior minimalista. Aplique as regras estritas de "Design Taste":
- WHITESPACE: Adicione margens generosas entre todos os blocos de informação. Não esprema o conteúdo.
- TIPOGRAFIA: Use contraste extremo de tamanho e peso entre Títulos e Texto de Apoio.
- MINIMALISMO: Remova linhas, bordas e decorações inúteis. Prefira o espaço em branco para separar os elementos.
- ESTRUTURA: Use um layout limpo, listado ou em grid simples, evitando mapas mentais confusos.
```

## Aplicação Prática
Se o usuário pedir: "Melhore esse design", não adicione elementos. A melhoria do *Design Taste* geralmente vem da **remoção** de ruído visual e do **aumento** do espaço negativo.
