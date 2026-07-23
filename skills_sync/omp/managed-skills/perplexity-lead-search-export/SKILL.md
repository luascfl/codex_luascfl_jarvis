---
name: perplexity-lead-search-export
description: "Use CDP automation to search Perplexity for an existing lead in the OrganizeJr Space, extract DOM content, and save as enrichment evidence."
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/pp-leads-brasil/organizejr-pp-leads`

# Perplexity Lead Search & Export (OrganizeJr Space)

Use esta skill quando o usuário quiser reaproveitar uma pesquisa já existente no Perplexity sobre um lead.

Todos os leads da OrganizeJr ficam no Space oficial:
`https://www.perplexity.ai/spaces/organizejr-UBkvhDHVRV.qPSZzXNVuYw`

## Regra de arquitetura
Não deixe scripts auxiliares soltos no repositório para este fluxo. O comportamento canônico deve morar nesta própria skill.

Arquivos temporários e obsoletos como:
- `process_consultagro_final_scrolled.py`
- `process_consultagro_final.py`
- `process_consultagro.py`
- `process_leads_final.py`
- `process_leads_search.py`
- `process_leads.py`
- `test_nav.py`
- `click_cdp.py`
- `match.py`
- `export-perplexity-lead-search.py`

devem ser tratados como experimentos descartáveis e apagados depois que a lógica final for consolidada aqui.

## O que aproveitar do script antigo
Do script antigo `export-perplexity-lead-search.py`, só duas ideias continuam válidas:
1. gerar o slug do lead a partir do nome
2. salvar o `.md` em `organizejr-pp-leads/leads/<lead>/<lead>.perplexity-search.md`

Todo o resto daquele script deve ser descartado, porque ficou tecnicamente obsoleto.

## Por que o script antigo ficou obsoleto
O arquivo `export-perplexity-lead-search.py` não deve continuar vivo porque ele:
- tentava copiar/clonar perfil do Chrome
- usava busca global `/search?q=` em vez do Space da OrganizeJr
- dependia do botão `Export as Markdown`, que abre diálogo nativo e trava a automação
- seguia o caminho Playwright + staged profile, que foi superado pela arquitetura Chrome persistente + CDP

## Solução canônica
A solução correta exige 7 passos:
1. usar Chrome persistente via `hub` + CDP
2. abrir o Space oficial da OrganizeJr
3. clicar em `Pesquisar sessões`
4. digitar o nome do lead e esperar o filtro renderizar o resultado
5. achar o texto do lead, fazer `scrollIntoView`, pegar coordenadas e enviar clique nativo via CDP
6. esperar a URL mudar para `/search/...`
7. extrair o `innerText` e salvar em `organizejr-pp-leads/leads/<lead>/<lead>.perplexity-search.md`

## Script Python de referência único
Use este script, ou lógica idêntica, como fonte de verdade:

```python
import requests, websocket, json, time
from pathlib import Path

SPACE_URL = 'https://www.perplexity.ai/spaces/organizejr-UBkvhDHVRV.qPSZzXNVuYw'
LEAD = 'NOME_DO_LEAD_AQUI'

resp = requests.get('http://127.0.0.1:9222/json')
target_ws_url = next(tab['webSocketDebuggerUrl'] for tab in resp.json() if 'perplexity.ai' in tab.get('url', '').lower())
ws = websocket.WebSocket()
ws.connect(target_ws_url)

req_id = 1
def send(method, params=None):
    global req_id
    payload = {"id": req_id, "method": method, **({"params": params} if params else {})}
    ws.send(json.dumps(payload))
    req_id += 1
    while True:
        res = json.loads(ws.recv())
        if res.get("id") == req_id - 1:
            return res

def eval_js(expression):
    res = send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
    return res.get("result", {}).get("result", {}).get("value")

send("Page.navigate", {"url": SPACE_URL})

for _ in range(10):
    time.sleep(1)
    if eval_js("!!document.querySelector('[aria-label=\\"Pesquisar sessões\\"]')"):
        break

_ = eval_js("document.querySelector('[aria-label=\\"Pesquisar sessões\\"]').click()")

for _ in range(5):
    time.sleep(1)
    if eval_js("document.activeElement && document.activeElement.tagName === 'INPUT'"):
        eval_js(f"""
        (() => {{
            const input = document.activeElement;
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(input, '{LEAD}');
            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
            return true;
        }})();
        """)
        break

for _ in range(10):
    time.sleep(1)
    main_text = eval_js("document.querySelector('main') ? document.querySelector('main').innerText : ''") or ''
    if LEAD.lower() in main_text.lower():
        break

coords = eval_js(f"""
(() => {{
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
  let node;
  while ((node = walker.nextNode())) {{
    if (node.nodeValue.toLowerCase().includes('{LEAD.lower()}')) {{
      const p = node.parentElement;
      p.scrollIntoView({{block: 'center', inline: 'center', behavior: 'instant'}});
      const range = document.createRange();
      range.selectNodeContents(node);
      const rect = range.getBoundingClientRect();
      return {{x: rect.x + rect.width / 2, y: rect.y + rect.height / 2}};
    }}
  }}
  return null;
}})();
""")

if not coords:
    raise SystemExit(f'Lead não encontrado no Space: {LEAD}')

x, y = coords['x'], coords['y']
send('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
time.sleep(0.1)
send('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})

for _ in range(10):
    time.sleep(1)
    current_url = eval_js('window.location.href') or ''
    if '/search/' in current_url:
        break

text = eval_js("document.querySelector('main') ? document.querySelector('main').innerText : document.body.innerText") or ''
def slugify(value: str) -> str:
    import re
    value = value.casefold()
    value = re.sub(r'[^a-z0-9]+', '-', value)
    return value.strip('-') or 'lead'
folder_name = slugify(LEAD)
file_path = Path(f'/home/lucas/Downloads/pp-leads-brasil/organizejr-pp-leads/leads/{folder_name}/{folder_name}.perplexity-search.md')
file_path.parent.mkdir(parents=True, exist_ok=True)
file_path.write_text(f'# {LEAD.upper()} - Perplexity Session\n\n' + text, encoding='utf-8')
print(f'Salvo em {file_path}')
ws.close()
```

## Caminho de destino
Sempre salvar em:
`organizejr-pp-leads/leads/<lead-slug>/<lead-slug>.perplexity-search.md`

## Regra final de uso
- pesquisar o lead no próprio Space
- abrir um por vez
- extrair um por vez
- apagar scripts temporários do repo depois
- manter o comportamento final só na skill
