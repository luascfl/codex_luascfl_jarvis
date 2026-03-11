---
description: "Politica de commit e sincronizacao Git para projetos com GitHub e nuvem"
globs:
  - "**/*"
apply_to: alwaysOn
---

# Politica de commit e sincronizacao Git

Quando o projeto tiver remoto GitHub:

- toda mudanca relevante de codigo, configuracao, contexto ou documentacao deve terminar em commit
- nao encerrar ciclo relevante com working tree sujo sem justificativa explicita do usuario
- a referencia esperada e manter o branch local alinhado com o branch remoto correspondente

Quando o projeto tambem tiver workspace em nuvem ligado ao mesmo repositorio:

- use um branch dedicado para a nuvem quando esse fluxo existir
- nao deixe o workspace remoto como fonte isolada de drift nao commitado
- se uma mudanca nasceu na nuvem, ela deve virar commit no branch de sincronizacao e voltar ao fluxo Git principal

Regra de fechamento:

- em projeto com GitHub, fechamento de ciclo pede commit
- em projeto com GitHub e nuvem, fechamento de ciclo pede commit tambem no branch de sincronizacao quando houver impacto no ambiente remoto
- detalhes como nome do branch de sincronizacao, host remoto e politica de equivalencia entre local e nuvem pertencem ao contexto e workflow do projeto atual
