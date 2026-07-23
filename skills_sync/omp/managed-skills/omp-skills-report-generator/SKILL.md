---
name: omp-skills-report-generator
description: "Python script and workflow to dynamically scan, parse, group, and list all OMP skills across the system, identifying conflicts and merge candidates."
---

## Origem
Criada a partir do contexto: `Global`

# OMP Skills Report Generator

Use this skill whenever the user asks to list their skills (e.g., "lista minhas skills", "quais skills eu tenho"). Instead of manually checking directories, run the following Python script using the `eval` tool to generate an accurate, markdown-formatted report of all skills across the OMP ecosystems.

This script automatically:
1. Scans all relevant agent directories.
2. Extracts the `name` from YAML frontmatter.
3. Extracts the `## Origem` context.
4. Identifies duplicated skills (conflicts).
5. Groups and flags skills by origin for potential merges (ignoring `Global` and `Desconhecida` to preserve performance).

## Python Script

```python
import os
import glob
import re
import yaml
from collections import defaultdict

search_paths = [
    "~/.omp/agent/managed-skills/*/SKILL.md",
    "~/.omp/agent/skills/*/SKILL.md",
    "~/.omp/skills/*/SKILL.md",
    "~/.agents/skills/*/SKILL.md",
    "~/.gemini/skills/*/SKILL.md",
    "~/.codex/skills/*/SKILL.md",
    "./.omp/skills/*/SKILL.md"
]

skills = []
name_paths = defaultdict(list)
origin_groups = defaultdict(list)

for path_pattern in search_paths:
    expanded_pattern = os.path.expanduser(path_pattern)
    for file_path in glob.glob(expanded_pattern):
        folder_name = os.path.basename(os.path.dirname(file_path))
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            continue
            
        name = folder_name
        frontmatter_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        if frontmatter_match:
            try:
                fm = yaml.safe_load(frontmatter_match.group(1))
                if fm and 'name' in fm:
                    name = fm['name']
            except:
                pass
                
        origin = "Desconhecida (Skill Antiga/Legado)"
        origin_match = re.search(r'## Origem\s*(.*?)(?=\n##|\Z)', content, re.DOTALL | re.IGNORECASE)
        if origin_match:
            origin_text = origin_match.group(1).strip()
            path_match = re.search(r'`([^`]+)`', origin_text)
            if path_match:
                origin = path_match.group(1).strip()
            else:
                origin = origin_text.split('\n')[0].strip()
        
        if origin.lower() == "global":
            origin = "Global"
        
        skill_info = {
            'name': name,
            'path': os.path.dirname(file_path),
            'origin': origin
        }
        skills.append(skill_info)
        name_paths[name].append(skill_info['path'])
        origin_groups[origin].append(name)

output_md = "## Tabela Geral de Skills\n\n| Nome da Skill | Local de Instalação | Origem |\n|---|---|---|\n"
for s in sorted(skills, key=lambda x: x['name']):
    output_md += f"| {s['name']} | `{s['path']}` | {s['origin']} |\n"

conflicts = {name: paths for name, paths in name_paths.items() if len(paths) > 1}
output_md += "\n## ⚠️ Conflitos Encontrados\n\n"
if conflicts:
    for name, paths in conflicts.items():
        output_md += f"- A skill **`{name}`** está duplicada e foi encontrada em múltiplas pastas:\n"
        for p in paths:
            output_md += f"  - `{p}`\n"
else:
    output_md += "Nenhum conflito encontrado. O ambiente está limpo!\n"

output_md += "\n## 💡 Indicador de Mesclagem (Agrupamento por Origem)\n\n"
output_md += "*Nota: Conforme a nova regra de performance, origens `Global` ou `Desconhecida` não são agrupadas ou sugeridas para mescla, pois representam ferramentas universais ou de legado.*\n\n"

for origin, names in sorted(origin_groups.items(), key=lambda x: len(x[1]), reverse=True):
    if origin in ["Global", "Desconhecida (Skill Antiga/Legado)"]:
        continue
        
    count = len(names)
    if count > 1:
        output_md += f"- 🔴 **{count} skills** com origem em `{origin}` (Avaliar Mescla!):\n"
        for n in sorted(list(set(names))):
            output_md += f"  - `{n}`\n"
    elif count == 1:
        output_md += f"- 🟢 **1 skill** com origem em `{origin}`\n"

# Output or save the markdown
print(output_md)
```

## Workflow
1. Execute the Python script via `eval`.
2. Present the printed markdown output directly to the user.
