## Oracle Sync Workflow

Este arquivo documenta o fluxo operacional deste projeto para sincronizar o ambiente local com os workspaces do Oracle usados por OpenClaw e PicoClaw.

Este documento é específico deste projeto. Aqui ficam nomes de branch, host, caminhos remotos e a política concreta de equivalência entre local, GitHub e Oracle.

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

## Política obrigatória de sincronização

- Se houver mudança relevante neste projeto, ela deve terminar em commit.
- O branch local `main` deve convergir com `origin/main`.
- O branch local `oracle_picoclaw` deve convergir com `origin/oracle_picoclaw`.
- Os workspaces do Oracle não devem ficar como fonte isolada de drift. Se houve mudança lá, ela precisa virar commit em `oracle_picoclaw`, subir para o GitHub e voltar para o ambiente local.
- Se a mudança nasceu no local e precisa chegar ao Oracle, não basta copiar arquivo. O caminho correto é commit local, push, atualização de `oracle_picoclaw`, commit, push e pull nos workspaces do Oracle.

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

Depois faça commit em `oracle_picoclaw` se o merge ou ajuste gerar mudança nova.

### 3. Fazer push da branch `oracle_picoclaw`

```bash
cd /home/lucas/Downloads/codex_luascfl_jarvis
git push origin oracle_picoclaw
```

Se o GitHub pedir autenticação em HTTPS, use PAT no lugar de senha.

### 3.1 Garantir equivalência entre local e remoto

Depois do push:

```bash
cd /home/lucas/Downloads/codex_luascfl_jarvis
git fetch origin
git status -sb
git rev-parse main origin/main
git rev-parse oracle_picoclaw origin/oracle_picoclaw
```

O objetivo é não deixar `main` e `origin/main` divergentes sem decisão explícita, nem `oracle_picoclaw` e `origin/oracle_picoclaw` divergentes sem sincronização.

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

Se você fez alteração diretamente no Oracle antes de sincronizar:

```bash
cd /home/ubuntu/.openclaw/workspace/codex_luascfl_jarvis
git status
git add -A
git commit -m "sync: remote oracle change"
git push origin oracle_picoclaw
```

Depois puxe `oracle_picoclaw` no ambiente local para manter equivalência.

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
