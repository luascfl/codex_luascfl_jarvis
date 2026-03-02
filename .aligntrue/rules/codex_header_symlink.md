---
description: "Instrucao para corrigir header do Codex com AGENTS.md no projeto"
globs:
  - "**/*"
apply_to: alwaysOn
---

# Agents header no codex

O header do Codex mostra Agents.md como none quando nao existe um AGENTS.md dentro do diretorio do projeto. Isso acontece mesmo que o link global em ~/.codex/AGENTS.md esteja correto. Para manter o header consistente, crie um symlink do AGENTS.md global dentro do projeto.

Exemplo:

```bash
ln -s /home/lucas/Downloads/codex_luascfl/AGENTS.md /caminho/do/projeto/AGENTS.md
```

Para este projeto:

```bash
ln -s /home/lucas/Downloads/codex_luascfl/AGENTS.md /home/lucas/Downloads/codex_luascfl/super_mcp_servers/AGENTS.md
```
