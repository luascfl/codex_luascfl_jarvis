---
description: Revisar outra resposta com niveis de confianca e sugerir checagens adicionais
argument-hint: [TEXTO="<trecho>"]
---

Use esta skill para revisar o texto fornecido em $TEXTO ou no argumento posicional correspondente. O objetivo e:

1. Extrair as afirmacoes principais ou passos relevantes.
2. Para cada afirmacao, indicar o nivel de confianca (0-100%) respaldado por evidencias locais (dados da conversa, trechos de codigo, referencias) ou pela ausencia delas.
3. Sinalizar o que ficaria mais confiavel com verificacoes externas e propor proximos passos para confirmar.
4. Terminar resumindo quais afirmacoes sao confiantes (>80%), duvidosas (40-80%) e quais precisam de confirmacao urgente (<40%).

Formato recomendado por afirmacao:
- Afirmacao: [texto curto]
  - Confianca: XX% (motivo ou referencia)
  - Acao sugerida: (se necessario)

Ao invocar o prompt, mencione o idioma desejado (portugues e padrao se o texto original estiver em portugues). Se for util, reescreva a conclusao com base nas afirmacoes que passaram no exame.
