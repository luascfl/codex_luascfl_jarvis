---
name: github-downloads-sync-check
description: "Verificação de repositórios via Python dinâmico, detecção de Hubs (topic hub, codex_, releases), prevenção de submódulos e auditoria de sistema."
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/send_folder_to_github`

Quando o usuário pedir para verificar quais repositórios do GitHub estão na pasta Downloads (ou vice-versa) ou quiser enviar pastas para o GitHub, siga este procedimento:

### 1. Obter os dados remotos e locais
Use a ferramenta `eval` com a linguagem `py` para rodar o script abaixo. Este script já resolve TODA a lógica: ele busca os repositórios remotos via `gh api`, lista as pastas locais com profundidade 4, classifica Hubs (pela tag 'hub' no GitHub, pastas `codex_` ou pastas `releases`), identifica Submódulos e imprime a tabela em Markdown prontinha.

Rode o seguinte código no `eval`:
```python
import os
import subprocess

def is_hub_name(name):
    """Regra centralizada: um repo é Hub se começa com codex_ ou releases."""
    return name.startswith("codex_") or name.startswith("releases")

try:
    gh_output = subprocess.check_output("gh api user/repos --paginate -q '.[].name'", shell=True, text=True)
    remote_repos = gh_output.strip().splitlines()
    
    gh_topics_output = subprocess.check_output("gh api user/repos --paginate --jq '.[] | select(.topics[]? == \"hub\") | .name'", shell=True, text=True)
    remote_hubs = set(gh_topics_output.strip().splitlines())
except Exception as e:
    remote_repos = []
    remote_hubs = set()

try:
    find_cmd = "find /home/lucas/Downloads -maxdepth 4 -name '.git' | sed 's|/.git$||'"
    find_output = subprocess.check_output(find_cmd, shell=True, text=True)
    local_paths = find_output.strip().splitlines()
except Exception as e:
    local_paths = []

remote_set = set(remote_repos)

hubs = set()
for path in local_paths:
    is_hub = any(p != path and p.startswith(path + '/') for p in local_paths)
    if is_hub:
        hubs.add(path)

repo_classification = {}
local_map = {}
for path in local_paths:
    name = os.path.basename(path)
    local_map[name] = path
    is_submodule = any(path != h and path.startswith(h + '/') for h in hubs)
    
    is_hub = path in hubs or name in remote_hubs or is_hub_name(name)
    
    if is_hub and is_submodule:
        repo_classification[name] = "🏢📦 [SUBMÓDULO E HUB]"
    elif is_hub:
        repo_classification[name] = "🏢 [HUB]"
    elif is_submodule and name.startswith("tmp_"):
        repo_classification[name] = "🔒📦 [SUBMÓDULO PRIVADO]"
    elif is_submodule:
        repo_classification[name] = "📦 [SUBMÓDULO]"
    elif name.startswith("tmp_"):
        repo_classification[name] = "🔒 [PRIVADO]"
    else:
        repo_classification[name] = "📄 [NORMAL]"

for name in remote_repos:
    if name not in repo_classification:
        if name in remote_hubs or is_hub_name(name):
            repo_classification[name] = "🏢 [HUB]"
        elif name.startswith("tmp_"): 
            repo_classification[name] = "🔒📦 [SUBMÓDULO PRIVADO]"
        else:
            repo_classification[name] = "📄 [NORMAL]"

all_repos = set(remote_repos).union(set(local_map.keys()))

print("| Nome do Repositório | Tipo | Situação (Status) | Caminho Local |")
print("| :--- | :--- | :--- | :--- |")

count_hidden = 0
for name in sorted(all_repos, key=lambda x: x.lower()):
    in_remote = name in remote_set
    in_local = name in local_map
    
    if in_local and in_remote:
        continue # Oculta os perfeitamente sincronizados para focar nas divergências
    elif in_local and not in_remote:
        status = "💻 Apenas no Downloads"
        path = local_map[name]
    else:
        status = "☁️ Apenas no GitHub"
        path = "-"
        
    repo_type = repo_classification.get(name, "📄 [NORMAL]")
    lines.append(f"| **{name}** | {repo_type} | {status} | {path} |")

lines.append(f"\n*({count_synced} repositórios Sincronizados omitidos.)*")
print("\n".join(lines))
```

*(O script omite apenas os Sincronizados. Mostra tanto "Apenas no GitHub" quanto "Apenas no Downloads".)*

### 2. Regra de Ouro: Arquitetura de Hubs
- Todos os Hubs DEVEM existir localmente na pasta `~/Downloads` (nível raiz). Sem exceção.
- Se a tabela mostrar um Hub como "Apenas no GitHub", clone-o imediatamente em `~/Downloads` sem perguntar.
- Um repo é Hub se: tem o tópico `hub` no GitHub, OU o nome começa com `codex_`, OU o nome começa com `releases`.
- Um Hub pode conter outros Hubs como submódulos ("Hub dos Hubs"), como é o caso de `automacoes`.
- Essa regra está centralizada na função `is_hub_name()` do script Python acima.
- O script `create_and_push_repo.sh` usa a mesma convenção via `detect_repo_flavor()`.

#### Ordem de clone dos Hubs
Quando houver Hubs faltando localmente, a ordem de clone é:
1. **Primeiro: Hub dos Hubs** (ex: `automacoes`). Ao clonar com `--recurse-submodules`, ele já traz consigo os submódulos que são Hubs filhos.
2. **Depois: Hubs independentes** que não vieram como submódulo de nenhum Hub dos Hubs.

Isso evita clonar um Hub avulso que já viria automaticamente como submódulo de um Hub-pai.

### 3. Auditoria de Gits Aninhados
Se a tabela revelar repositórios locais que estão caindo como `[SUBMÓDULO]` mas você não tem certeza se deveriam ser, pergunte ao usuário se a pasta oculta `.git` de dentro deles deve ser apagada para virarem pastas normais.

### 4. Auditoria de Atalhos Quebrados do Sistema
Rode um `grep` buscando pelos nomes dos repositórios locais nas pastas críticas (`~/.bashrc`, `~/.config/systemd/user/`, etc) e avise se houver caminhos quebrados.

### 5. Upload usando a ferramenta oficial
Para enviar uma pasta local (marcada como 💻 Apenas no Downloads), utilize o script oficial:
```bash
cd /caminho/para/a/pasta/alvo
export GIT_SSH_COMMAND="ssh -i ~/.ssh/github_luascfl_ed25519 -o IdentitiesOnly=yes"
/home/lucas/Downloads/send_folder_to_github/create_and_push_repo.sh
```
Se for o push de um HUB, rode o script na raiz do HUB.
