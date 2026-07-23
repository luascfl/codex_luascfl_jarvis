---
name: debt-contestation-portal-automation
description: "Browser automation rules for debt contestation portals, mapping fallback selectors, and the manual complaint protocol when bots are blocked."
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/contestação_divida`

# Automação de Portais e Fallbacks de Contestação

Esta skill consolida as diretrizes para automatizar o preenchimento em portais de consumidor (ex: Consumidor.gov.br, Serasa) e o protocolo de escape (fallback) quando as automações falham.

## 1. Mapeamento de Seletores em Portais (`portal-mapping`)
Use este fluxo quando a automação de navegador falhar ao preencher campos devido a seletores dinâmicos ou desconhecidos.

**Procedimento:**
1. **Dump de seletores:** Abra o portal alvo e liste os campos disponíveis.
   ```bash
   node dist/src/cli.js browser-dump <target-url> --profile-dir .private/browser-profiles/<channel>
   ```
2. **Revisão:** Analise o JSON de saída procurando por atributos `name`, `testid`, `ariaLabel` ou `placeholder`.
3. **Mapear e Sobrescrever:**
   - Adicione os novos seletores no `DEFAULT_SELECTORS` do código base ou crie um mapa de substituição específico para o canal.
4. **Human-in-the-loop:** Sempre exija verificação humana dos campos pré-preenchidos antes de permitir que qualquer script clique no botão de envio final.

## 2. Fallback de Reclamação Manual (`manual-complaint`)
Se a automação de navegador for bloqueada por sistemas anti-bot, WAFs rigorosos ou captchas nos portais das empresas ou governo:

**Regra de Segurança:** Não force bypass de captcha e não sobrecarregue os servidores tentando evadir defesas nativas.

**Procedimento de Fallback:**
1. **Extrair o Rascunho (Draft):** Use a CLI para exportar o texto gerado e validado.
   ```bash
   node dist/src/cli.js complaint <case.json> <debtId> <channel>
   ```
2. **Acesso Manual:** Oriente o usuário a logar manualmente pelo próprio navegador.
3. **Copy/Paste:** O usuário deve copiar e colar o rascunho (payload formatado com CAIXA ALTA cirúrgica) diretamente no formulário do portal/SAC.
4. **Anexos:** O usuário anexa as evidências (previamente mescladas e comprimidas) manualmente.
5. **Gravação do Protocolo:** Após o envio, registre o protocolo no banco de dados local da CLI.
   ```bash
   node dist/src/cli.js record-protocol <case.json> <channel> "<summary>" --write <case.json>
   ```
