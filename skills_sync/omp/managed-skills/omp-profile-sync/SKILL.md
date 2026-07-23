---
name: omp-profile-sync
description: Sincroniza arquivos de configuração de um perfil Oh-My-Pi com o perfil padrão (default).
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/codex_luascfl_jarvis`

# Sincronização de Perfil Oh-My-Pi

Esta skill sincroniza as configurações de um perfil específico do Oh-My-Pi (`~/.omp/profiles/<nome>/agent/`) com as configurações padrão (`~/.omp/agent/`), garantindo consistência no ambiente.

## Procedimento

1. Compare a estrutura de diretórios e arquivos entre `~/.omp/agent/` e `~/.omp/profiles/<perfil>/agent/`.
2. Identifique divergências nos arquivos de configuração (`config.yml`, `settings.json`, etc.).
3. Leia o conteúdo dos arquivos de configuração padrão:
   - `read(path="~/.omp/agent/config.yml")`
   - `read(path="~/.omp/agent/settings.json")`
4. Aplique o conteúdo padrão nos respectivos arquivos do perfil alvo usando `write`:
   - `write(path="~/.omp/profiles/<perfil>/agent/config.yml", content=...)`
   - `write(path="~/.omp/profiles/<perfil>/agent/settings.json", content=...)`

## Quando usar
- Quando um novo perfil for criado e precisar de configurações padrão.
- Quando configurações de perfil estiverem obsoletas ou divergentes do padrão estabelecido.
- Como etapa de higiene após renomeação ou criação manual de perfis.
