---
name: debt-contestation-evidence-tools
description: "Tools for evidence merging, compression, Serasa PDF creditor identification via embedded logos, and protocol update automation."
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/contestação_divida`

# Processamento de Evidências e Ferramentas Forenses

Esta skill consolida as diretrizes para processar arquivos de evidência em casos de contestação de dívidas, incluindo compressão de PDFs, identificação de credores ocultos e atualização de protocolos.

## 1. Compressão e Mesclagem de Evidências
Use este procedimento quando houver muitos arquivos para upload em um portal (ex: limite de 5 arquivos ou 1MB).

**Regra Inegociável:**
- Mescle **apenas arquivos da mesma empresa e da mesma reclamação**.
- Nunca misture evidências de credores diferentes (ex: banco com telecom).
- Nomeie a saída explicitamente (ex: `evidencias-banco-somente.pdf`).

**Procedimento:**
1. Colete os arquivos filtrados por empresa.
2. Mescle usando `pypdf` (em Python):
   ```python
   from pypdf import PdfWriter, PdfReader
   writer = PdfWriter()
   for pdf_file in list_of_paths:
       reader = PdfReader(str(pdf_file))
       for page in reader.pages:
           writer.add_page(page)
   with open("consolidado.pdf", "wb") as f:
       writer.write(f)
   ```
3. Comprima usando Ghostscript para caber nos limites do portal:
   ```bash
   gs -sDEVICE=pdfwrite -dCompatibilityLevel=1.4 -dPDFSETTINGS=/screen -dNOPAUSE -dQUIET -dBATCH -sOutputFile=comprimido.pdf consolidado.pdf
   ```

## 2. Identificação de Credor Oculto (Serasa)
Plataformas como o Serasa escondem o nome real do credor cedente atrás de textos genéricos ("Grupo de dívidas no CPF"). Porém, a logomarca do credor é embutida no documento.

**Como identificar:**
1. Extraia as imagens brutas do PDF com `pdfimages`:
   ```bash
   pdfimages -png "caminho/para/ofertas-serasa.pdf" "pasta_destino/logo"
   ```
2. Liste os arquivos (`ls -l`). Ícones de UI são muito pequenos (<5KB). Os logos dos bancos variam de 8KB a 35KB.
3. Leia as imagens médias via ferramenta `read` e use a Visão da IA para ler as marcas (ex: "Claro", "Vivo", "Recovery") e correlacioná-las cronologicamente às entradas anônimas do PDF.

## 3. Atualização Automatizada de Protocolos
Para integrar novas atualizações de protocolos (ex: Consumidor.gov.br) no registro local de casos:

1. **Extrair PDFs de andamento:** Salve novos PDFs (ex: `Reclamação 123 - Banco.pdf`) em `.private/<caso>/` e extraia o texto via `read()`.
2. **Atualizar `case.private.json`:**
   - Identifique os protocolos existentes na seção `protocols`.
   - Atualize `responseSummary`, `responseClassification` e `nextAction` com script seguro em Python.
3. **Adicionar notas:** Insira um log descritivo na seção `notes` do JSON.
4. **Validar:** Rode o CLI do projeto para garantir a integridade da estrutura: `node dist/src/cli.js validate .private/<caso>/case.private.json`.
