---
name: omp-interactive-pty
description: Generate and validate interactive PTY probes and wrappers compatible with Oh-My-Pi, including sudo prompts, TERM setup, TTY checks, resize propagation, logging, timeouts, presets, and JSON diagnostics.
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/tmux_qterminal_setup`

# OMP interactive PTY

Use esta skill quando o usuário quiser replicar o comportamento de PTY interativo do Oh-My-Pi para qualquer script, prompt, `sudo`, `python`, `bash`, `vim`, `top` ou outro programa que exija TTY real.

## Como o Oh-My-Pi faz isso

O caminho de PTY do OMP depende de:
1. `pty: true`
2. contexto com UI
3. `PI_NO_PTY != 1`

Quando essas condições são verdadeiras, o OMP aloca um PTY real, encaminha o teclado do usuário para o PTY e roda o child com um terminal de verdade. É por isso que `sudo` consegue pedir senha sem sair do OMP.

## O que um wrapper compatível precisa fazer

Para replicar esse comportamento fora do runtime interno do OMP, o script precisa:
- alocar um PTY real
- ligar `stdin/stdout/stderr` do child ao lado slave do PTY
- encaminhar o teclado do processo pai ao master quando o pai tiver TTY
- propagar resize (`SIGWINCH`)
- forçar `TERM=xterm-256color`
- opcionalmente registrar output, timeout e diagnóstico estruturado

## Arquivos canônicos da origem

No projeto de origem, use ou copie estes arquivos:
- `/home/lucas/Downloads/tmux_qterminal_setup/omp_pty_probe.py`
- `/home/lucas/Downloads/tmux_qterminal_setup/omp_pty_wrapper.py`
- `/home/lucas/Downloads/tmux_qterminal_setup/omp_pty_prompt_test.py`

## Quando usar cada arquivo

### `omp_pty_probe.py`
Use para provar que o child realmente vê um PTY.

Executar:
```bash
python3 omp_pty_probe.py
```

Resultado esperado:
- `stdin_isatty: true`
- `stdout_isatty: true`
- `stderr_isatty: true`
- `tty_name: /dev/pts/...`
- `term: xterm-256color`

### `omp_pty_wrapper.py`
Use para interação real com o child.

Exemplos:
```bash
python3 omp_pty_wrapper.py -- bash
python3 omp_pty_wrapper.py -- python3
python3 omp_pty_wrapper.py -- sudo -k id
python3 omp_pty_wrapper.py -- top
python3 omp_pty_wrapper.py -- vim
```

### `omp_pty_prompt_test.py`
Use para validar input/echo sem depender de `vim` ou `top`.

Executar:
```bash
python3 omp_pty_wrapper.py -- python3 omp_pty_prompt_test.py
```

Fluxo esperado:
```text
Digite algo: banana
Recebi: banana
```


## Suporte a colar / bracketed paste

Em terminais como QTerminal, colar pode envolver o texto com as sequências `ESC[200~` e `ESC[201~` (bracketed paste).

Para prompts simples (`input()`, `bufio.Reader`, `sudo`, etc.), o wrapper deve remover esses marcadores antes de encaminhar o texto ao child.

No wrapper canônico da origem, isso é tratado normalizando o input do pai antes de escrever no PTY. O comportamento esperado é que colar `banana` resulte em:

```text
Digite algo: banana
Recebi: banana
```

Se o usuário relatar `^[[200~...^[[201~` aparecendo no prompt, revise primeiro o wrapper PTY e confirme que ele remove bracketed paste.

## Recursos da versão atual do wrapper

O wrapper atual suporta:
- `--log <arquivo>`
- `--timeout <segundos>`
- `--preset bash|python|top|vim`
- `--json`

Exemplos:
```bash
python3 omp_pty_wrapper.py --preset python
python3 omp_pty_wrapper.py --log /tmp/omp_pty_wrapper.log -- python3 -c 'print("log-ok")'
python3 omp_pty_wrapper.py --timeout 1 --json -- bash -lc 'sleep 2'
```

## Receita de validação mínima

1. Probe PTY:
```bash
python3 omp_pty_probe.py
```

2. Wrapper com TERM, size e tty:
```bash
python3 omp_pty_wrapper.py -- bash -lc 'printf "TERM=%s\n" "$TERM"; stty size; python3 -c "import os,sys; print(os.isatty(0), os.ttyname(0))"'
```

3. Prompt mínimo:
```bash
python3 omp_pty_wrapper.py -- python3 omp_pty_prompt_test.py
```

4. Sudo real:
```bash
python3 omp_pty_wrapper.py -- sudo -k id
```

## Resultado esperado

No final, o usuário deve conseguir:
- abrir `bash`, `python`, `top`, `vim` e `sudo` no wrapper
- digitar normalmente
- ver `/dev/pts/*` no child
- confirmar `TERM=xterm-256color`
- validar timeouts, logging e JSON diagnóstico quando necessário

## Regra operacional

Quando o pedido for “gerar e validar um PTY interativo compatível com OMP”, siga esta ordem:
1. gerar ou copiar o probe
2. gerar ou copiar o wrapper
3. gerar o prompt mínimo
4. validar o child PTY
5. validar input/echo
6. validar `sudo` quando fizer sentido
7. só então afirmar que a compatibilidade foi reproduzida
