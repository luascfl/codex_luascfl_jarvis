---
name: export-vm-scripts
description: Exporta userscripts do Violentmonkey para Tampermonkey via leitura direta do IDB.
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/automacoes/userscripts/violentmonkey-tampermonkey-migrator`

# Exportação e Migração de Userscripts (Violentmonkey para Tampermonkey)

Este procedimento exporta scripts do Violentmonkey no Firefox/LibreWolf (mesmo se o navegador não abrir) e os migra para o formato Tampermonkey.

## Requisitos
- Python 3
- `pip install python-snappy`

## Passo a Passo

1. **Localize os scripts:**
   Certifique-se de que o LibreWolf ou Firefox esteja fechado.

2. **Execute o Exportador:**
   O script abaixo detecta o perfil do navegador, encontra o IndexedDB do Violentmonkey, descomprime os dados Snappy, decodifica o formato Structured Clone (SC) do Firefox e gera um arquivo ZIP.

   ```bash
   python3 exportar_violentmonkey.py
   ```

3. **Migre para Tampermonkey:**
   Após gerar o arquivo `violentmonkey_export.zip`, execute o script de migração para formatar corretamente para o Tampermonkey:

   ```bash
   python3 migrar_violentmonkey_para_tampermonkey.py violentmonkey_export.zip
   ```

4. **Resultado:**
   A pasta `tampermonkey_import/` conterá os arquivos `.user.js` prontos para importação no Tampermonkey.

## Notas Técnicas
- O Violentmonkey armazena scripts no IndexedDB do Firefox usando uma compressão Snappy envolta no formato de serialização Structured Clone.
- Este script `exportar_violentmonkey.py` resolve isso lendo o banco SQLite diretamente e realizando o processo inverso de decodificação.
