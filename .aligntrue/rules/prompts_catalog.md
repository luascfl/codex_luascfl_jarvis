# 📜 Catálogo de Prompts & Skills (AGCAO)

Este documento descreve os prompts especializados disponíveis no ecossistema (Gemini, Codex, etc.) e como criar novos.

## 🧠 Brainstorm & Criatividade
**Comando:** `/brainstorm` (Gemini) ou `/prompts:brainstorm` (Codex)
**Objetivo:** Transformar uma ideia vaga em um conceito sólido através de um loop iterativo.
**Mecânica:** 1 Pergunta + 1 Sugestão por turno.
**Quando usar:** Início de projetos, bloqueio criativo.

---

## 🏗️ Gestão de Projetos (AI Coders Context + GSD + Ralph + Gemini)
**Comando:** `/projeto` (Gemini) ou `/prompts:projeto` (Codex)
**Objetivo:** Operar como orquestrador de execução com contexto eficiente, baixo risco de bug e rastreabilidade.
**Mecânica:** Classifica se o projeto está novo, parcial ou operacional. Se faltarem entrypoints canônicos, roda bootstrap de contexto via workflow. Se faltar `.context/prd_ralph/prd.json`, faz bootstrap automático de PRD via skill `prd` no Codex. Se faltar `.context/docs/planning_gsd/PROJECT.md`, faz bootstrap de planejamento GSD. Depois planeja milestones, escolhe 1 story por ciclo no Ralph e prepara prompt fechado para o Gemini executor.
**Quando usar:** Início de projeto, retomada de contexto e definição do próximo ciclo de execução.

---



## ✅ Verificação de Confiança
**Comando:** `/prompts:confidence-check`
**Objetivo:** Validar soluções críticas antes do deploy.

---

## ⚙️ Guia Técnico: Criando Novos Prompts

O sistema AGCAO sincroniza prompts automaticamente.

1.  **Crie o arquivo:** Salve um arquivo Markdown em `prompts/<nome>.md`.
2.  **Adicione Metadados:** O arquivo deve começar com o frontmatter YAML:
    ```markdown
    ---
    description: "Descrição curta do que o prompt faz"
    ---
    # Título do Prompt
    ...instruções...
    ```
3.  **Sincronize:** Rode `python3 jarvis.py mcp-sync-clients`.
