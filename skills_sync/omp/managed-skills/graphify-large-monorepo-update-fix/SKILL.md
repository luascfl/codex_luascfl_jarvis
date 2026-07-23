---
name: graphify-large-monorepo-update-fix
description: Use when graphify update reaches 100% AST extraction and appears stuck on a large repository or after moving graphify outputs under .context/graphify-out.
---

## Problem pattern

`graphify update .` prints `AST extraction: ... (100%)` and then appears frozen for many minutes. On large repositories this can be post-extraction work, not file parsing:

- global raw-call resolution across hundreds of thousands of `raw_calls`;
- full Leiden/Louvain clustering on very large graphs;
- no progress logs after the 100% AST line.

## Diagnostic steps

1. Read the installed Graphify code, especially:
   - `graphify/extract.py`, function `extract`;
   - `graphify/watch.py`, function `_rebuild_code`;
   - `graphify/cluster.py` if clustering is suspected.
2. Count cached extraction size before rerunning long commands:

```python
from pathlib import Path
from graphify.detect import detect
from graphify.cache import load_cached
repo = Path('/path/to/repo')
d = detect(repo)
code_files = [Path(f) for f in d['files']['code']]
raw = nodes = edges = miss = 0
for p in code_files:
    c = load_cached(p, repo)
    if c is None:
        miss += 1
        continue
    nodes += len(c.get('nodes', []))
    edges += len(c.get('edges', []))
    raw += len(c.get('raw_calls', []))
print({'files': len(code_files), 'cache_missing': miss, 'nodes': nodes, 'edges': edges, 'raw_calls': raw})
```

## Patch approach

For very large monorepos, preserve correctness of the core AST graph while avoiding pathological post-processing:

1. In `graphify/extract.py` after the final 100% print, add flushed phase logs:
   - `merging per-file results`;
   - `resolving cross-file imports`;
   - `resolving N raw calls`.
2. Guard global raw-call resolution:
   - compute `raw_call_count = sum(len(result.get('raw_calls', [])) for result in per_file)`;
   - if `raw_call_count > 200_000`, print a clear skip message and do not build the global callee map;
   - otherwise run the original raw-call resolution.
3. In `graphify/watch.py`, add flushed phase logs around:
   - `build_from_json`;
   - clustering;
   - scoring;
   - report analysis.
4. For graphs above `50_000` nodes, avoid full clustering in code-only update. Use deterministic top-level source-path buckets instead:

```python
def _fast_source_communities(G) -> dict[int, list[str]]:
    buckets: dict[str, list[str]] = {}
    for node_id, data in G.nodes(data=True):
        source = data.get('source_file') or '_semantic'
        key = source.split('/', 1)[0] if '/' in source else source
        buckets.setdefault(key, []).append(node_id)
    ordered = sorted(buckets.values(), key=len, reverse=True)
    return {cid: sorted(nodes) for cid, nodes in enumerate(ordered)}
```

Then use it in `_rebuild_code`:

```python
G = build_from_json(result)
node_count = G.number_of_nodes()
edge_count = G.number_of_edges()
if node_count > 50_000:
    print(f'[graphify watch] Large graph ({node_count} nodes, {edge_count} edges) - using fast source-path communities instead of full clustering.', flush=True)
    communities = _fast_source_communities(G)
else:
    print(f'[graphify watch] Clustering {node_count} nodes...', flush=True)
    communities = cluster(G)
```

## Verification

Run:

```bash
python3 -m py_compile /path/to/site-packages/graphify/extract.py
python3 -m py_compile /path/to/site-packages/graphify/watch.py
graphify update .
```

Expected after 100%:

```text
AST extraction: merging per-file results
AST extraction: resolving cross-file imports
AST extraction: resolving N raw calls
AST extraction: skipped global raw-call resolution for large corpus (... calls)
[graphify watch] Building NetworkX graph...
[graphify watch] Large graph (... nodes, ... edges) - using fast source-path communities instead of full clustering.
[graphify watch] Rebuilt: ... nodes, ... edges, ... communities
```

`graph.html` may be skipped for graphs above 5,000 nodes. That is expected. The required outputs are `graph.json` and `GRAPH_REPORT.md`.
