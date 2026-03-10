## Oracle Sync Workflow

Este arquivo documenta o fluxo operacional deste projeto para sincronizar o ambiente local com os workspaces do Oracle usados por OpenClaw e PicoClaw.

## Escopos

- **Contexto de projeto**: fica em `.context/docs/`.
- **Branch de trabalho local**: `main`.
- **Branch de sincronização com Oracle**: `oracle_picoclaw`.
- **Workspaces remotos no Oracle**:
  - `/home/ubuntu/.openclaw/workspace/codex_luascfl_jarvis`
  - `/home/ubuntu/.picoclaw/workspace/codex_luascfl_jarvis`

## Repositório remoto canônico

Use sempre este remote:

```bash
git remote set-url origin https://github.com/luascfl/codex_luascfl_jarvis.git
```

Não use o repositório antigo `codex_luascfl.git`.

## Fluxo recomendado

### 1. Trabalhar localmente

Faça as mudanças no repositório local, normalmente em `main`.

```bash
cd /home/lucas/Downloads/codex_luascfl_jarvis
git status
```

### 2. Levar as mudanças para a branch do Oracle

Quando a mudança precisar chegar ao Oracle, atualize `oracle_picoclaw` com o conteúdo desejado.

Exemplo simples, a partir do repositório local:

```bash
git checkout main
git checkout oracle_picoclaw
git merge main
```

Se `oracle_picoclaw` estiver preso a um worktree, use o worktree dedicado.

Exemplo com worktree temporário:

```bash
git worktree add /tmp/codex_luascfl_jarvis_oracle oracle_picoclaw
cd /tmp/codex_luascfl_jarvis_oracle
git merge main
```

### 3. Fazer push da branch `oracle_picoclaw`

```bash
cd /home/lucas/Downloads/codex_luascfl_jarvis
git push origin oracle_picoclaw
```

Se o GitHub pedir autenticação em HTTPS, use PAT no lugar de senha.

### 4. Atualizar o Oracle remoto

Entre no servidor correto. Não use `~/.openclaw` no computador local. Esse caminho existe no Oracle, dentro do usuário `ubuntu`.

```bash
ssh ubuntu@mcp-instance
```

Atualize os dois workspaces remotos:

```bash
for repo in \
  /home/ubuntu/.openclaw/workspace/codex_luascfl_jarvis \
  /home/ubuntu/.picoclaw/workspace/codex_luascfl_jarvis
do
  cd "$repo"
  git remote set-url origin https://github.com/luascfl/codex_luascfl_jarvis.git
  git fetch origin
  git switch oracle_picoclaw || git switch -c oracle_picoclaw --track origin/oracle_picoclaw
  git pull --rebase origin oracle_picoclaw
done
```

### 5. Reiniciar serviços, se necessário

```bash
systemctl --user restart openclaw-gateway
systemctl --user restart picoclaw-gateway
```

## Problemas comuns

### Permissão negada em refs ou logs do Git

Se você rodou comandos com `sudo` e o Git ficou com arquivos do `.git` como `root`, corrija antes de continuar:

```bash
cd /home/lucas/Downloads/codex_luascfl_jarvis
sudo chown -R $USER:$USER .git /tmp/codex_luascfl_jarvis_oracle
```

### Branch em uso por worktree

Se `oracle_picoclaw` já estiver anexada a um worktree, não tente fazer `git switch oracle_picoclaw` no diretório principal. Use o worktree dedicado em `/tmp/codex_luascfl_jarvis_oracle`.

### Contexto errado

As instruções operacionais deste projeto devem ficar em `.context/docs/`. Não use AlignTrue para armazenar este fluxo operacional específico do projeto.
