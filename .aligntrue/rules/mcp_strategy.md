# 🧠 MCP Orchestration Strategy & Tooling Guide

Este documento instrui o Agente sobre como orquestrar as ferramentas MCP ativas de forma objetiva no workflow restrito.

## 🛠️ Inventário de Ferramentas Ativas

| Servidor / Namespace | Ferramentas Chave | Função Primária | Disponibilidade |
| :--- | :--- | :--- | :--- |
| **Jarvis (Core)** | `gtasks_*`, `gcal_*`, `rag_*`, `editorial_*`, `sequential_thought` | Execução operacional, agenda, memória local e qualidade | ✅ Todos |
| **Brave Search** | `brave_web_search` | Pesquisa web rápida | ⚠️ Apenas Codex |
| **AI Coders Context** | `analysis`, `structure` | Mapeamento e leitura estrutural do projeto | ⚠️ Apenas Codex |

---

## 🚦 Matriz de Decisão (Gatilhos de Contexto)

### 1. Contexto: Planejamento & Execução
**Gatilho:** "o que fazer agora", "planeje a fase", "executar story".
* **Planejamento macro:** GSD em `.context/docs/planning_gsd/`.
* **Execução incremental:** Ralph com PRD ativo em `.context/prd_ralph/prd.json`.
* **Tarefas pessoais/calendário:** `jarvis:gtasks_*` e `jarvis:gcal_*`.

### 2. Contexto: Memória & Conhecimento
**Gatilho:** "busque nos docs", "o que decidimos", "resuma contexto".
* **Ação primária:** `jarvis:rag_search`.
* **Indexação quando houver material novo:** `jarvis:rag_index`.

### 3. Contexto: Código & Arquitetura
**Gatilho:** "mapeie dependências", "entenda impacto", "como esse módulo se conecta".
* **No Codex:** use AI Coders Context para mapa estrutural e dependências.
* **Fallback:** use busca local por arquivo quando necessário.

### 4. Contexto: Web & Escrita
**Gatilho:** "acesse o site", "valide fluxo", "revise texto", "analise SEO".
* **Web interativa:** use navegador apenas quando necessário.
* **Escrita e revisão:** `editorial_*`, `audit_seo`, `speedgrapher_fog_index`.

---

## ⚠️ Restrições

1. Operar no modo restrito: `gsd + ralph + ai-coders-context`.
2. Contexto único: `.context/docs` + `README.md` + `.context/docs/planning_gsd/STATE.md` + `.context/prd_ralph/README.md`.
3. Fechamento de ciclo obrigatório: evidências técnicas e atualização de contexto.
