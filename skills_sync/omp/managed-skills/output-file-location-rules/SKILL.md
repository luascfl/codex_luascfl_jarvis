---
name: output-file-location-rules
description: "User preference: NEVER use /tmp/ for generating reports, automation outputs, or temporary files. Always save outputs directly in the active project directory."
---

## Origem
Criada a partir do contexto: `Global`

# Regras de localização de arquivos e outputs

Ao gerar arquivos de relatório, extrações de dados, resultados de automação, JSONs de resposta de scraping, scripts auxiliares ou qualquer arquivo temporário para análise, siga estas regras.

## 1. Proibição do `/tmp/`

Nunca utilize o diretório `/tmp/` do Linux para salvar arquivos gerados, a menos que seja um requisito estrito do sistema, como sockets ou pipes de IPC.

O usuário rejeita explicitamente o uso do `/tmp/` para despejo de arquivos de automação, relatórios ou arquivos temporários comuns.

## 2. Diretório de trabalho

Sempre grave os arquivos no diretório do projeto atual ou no subdiretório de contexto em que você está operando.

Exemplo: se estiver operando em um script dentro de `criar_trilha/gestor_x/`, salve os resultados como `criar_trilha/gestor_x/resultado.json`.

Isso garante que os dados fiquem isolados no escopo correto do projeto e não se percam nem sujem o sistema operacional.

## 3. Limpeza

Se precisar criar um arquivo provisório para uma ferramenta ler, como um script Python ou JSON intermediário, limpe-o imediatamente após o uso ou gere o conteúdo em memória via `eval`.
