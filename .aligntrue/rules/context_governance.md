---
description: "Protocolos de integridade de contexto, higiene de arquivos e hierarquia de regras."
globs:
  - "**/*"
apply_to: alwaysOn
---

# 🛡️ Governança de Contexto & Higiene

Estas regras garantem que o Agente nunca opere "cego" e mantenha a documentação limpa.

## 1. Protocolo de Visão (Context Check)
Ao iniciar uma sessão ou antes de tarefas complexas, verifique silenciosamente se você tem acesso de leitura ao contexto global (`../AGENTS.md` ou `~/.codex/AGENTS.md`).
- **Se falhar:** PARE IMEDIATAMENTE. Avise o usuário:
  > 🚫 **ERRO CRÍTICO DE PERMISSÃO:** Não consigo ler as regras globais. Por favor, rode: `sudo chown $USER:$USER ../AGENTS.md`

## 2. Higiene Documental (Zero Lixo)
O `README.md` é a fachada do projeto.
- **PROIBIDO:** Colocar logs brutos, outputs de terminal, dumps de `grep` ou base64 no `README.md`.
- **Alternativa:** Salve logs em arquivos `.log` (ex: `server.log`, `install.log`) e apenas mencione-os.
- **Exceção:** Pequenos snippets de erro (1-3 linhas) são permitidos em seções de "Troubleshooting".

## 3. Hierarquia de Verdade
1. **Projeto Local (`./AGENTS.md`):** Regras de infraestrutura (IPs, Comandos, Venvs) específicas deste projeto.
2. **Global (`../AGENTS.md`):** Comportamento padrão e ferramentas genéricas.
3. **AI Context (`.context/`):** Detalhes técnicos profundos (Arquitetura, Mapas).

Se você encontrar um `AGENTS.md` local, leia-o com prioridade máxima. Ele contém o "Como Rodar" deste ambiente específico.

## 4. Fluxo de Atualização (Sync)
Para aplicar novas regras ou propagar mudanças:
1. Edite os arquivos em `.aligntrue/rules/`.
2. Rode `python3 jarvis.py mcp-sync-clients` na raiz.
3. O script cuida da compilação e distribuição. Não rode `aligntrue` manualmente.
