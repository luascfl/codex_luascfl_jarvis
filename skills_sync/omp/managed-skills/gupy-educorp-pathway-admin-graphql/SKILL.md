---
name: gupy-educorp-pathway-admin-graphql
description: "Use when Gupy EduCorp admin UI pathway settings need verification or updates that the public API does not expose, especially section start_at/finish_at dates and manager versus participant separation."
---

# Gupy EduCorp pathway admin GraphQL

Use the public API first for read-only fields it exposes. When the needed pathway admin setting is not exposed, use the authenticated admin browser session and the page's own Apollo client instead of brittle DOM field filling.

## Critical distinctions

- The public API may return pathway `workload`, `isRequired`, and `settings`, but content section date ranges can be absent or `null` there.
- In the admin GraphQL model, `4. Conteúdo > Data de início e fim` persists on each topic/section as:
  - `sections[].start_at`
  - `sections[].finish_at`
- A raw DOM write to `#daterange` can look successful while not persisting. Verify with GraphQL after mutation.
- Managers are not participants. Keep managers only in `managersToAdd`. Never include names from `managersToAdd` in `participantsToAdd`.

## Browser prerequisites

Use the persistent CDP Chrome profile required by the browser rules:

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir=/home/lucas/.omp/chrome-persistent-profile
```

Open an authenticated Gupy admin page through `xd://browser` using `app.cdp_url = http://127.0.0.1:9222`.

## Query section dates through the page Apollo client

Inside `xd://browser` `run`, execute in the authenticated tab:

```js
return await tab.evaluate(async () => {
  let req = window.__wp_req;
  if (!req && Array.isArray(window.webpackChunkpathways)) {
    window.webpackChunkpathways.push([[Math.random()], {}, r => {
      req = r;
      window.__wp_req = r;
    }]);
  }
  const client = window.__APOLLO_CLIENT__;
  const query = req(13637).PathwaysDetail;
  const out = {};
  for (const id of ["45012", "44957", "45018"]) {
    const res = await client.query({query, variables: {id}, fetchPolicy: "network-only"});
    const p = res.data.pathway;
    out[id] = {
      title: p.title,
      sections: p.sections?.map(s => ({
        id: s.id,
        title: s.title,
        start_at: s.start_at,
        finish_at: s.finish_at,
      })),
    };
  }
  return out;
});
```

Expected persisted date shape for `22/07/2026` to `31/12/2026`:

```json
{
  "start_at": "2026-07-22T00:00:00.000Z",
  "finish_at": "2026-12-31T23:59:00.000Z"
}
```

## Update section dates through Apollo

Use the app's own `CreateOrUpdateTopic` mutation from webpack module `532`:

```js
return await tab.evaluate(async () => {
  let req = window.__wp_req;
  if (!req && Array.isArray(window.webpackChunkpathways)) {
    window.webpackChunkpathways.push([[Math.random()], {}, r => {
      req = r;
      window.__wp_req = r;
    }]);
  }
  const client = window.__APOLLO_CLIENT__;
  const mutation = req(532).CreateOrUpdateTopic;
  const targets = [
    {pathway_id: 45012, topic_id: 77599, title: "Seção 1"},
    {pathway_id: 45018, topic_id: 77603, title: "Seção 1"},
  ];
  const out = [];
  for (const t of targets) {
    const res = await client.mutate({
      mutation,
      variables: {
        createOrUpdateTopic: {
          ...t,
          start_at: "2026-07-22T00:00:00.000Z",
          finish_at: "2026-12-31T23:59:00.000Z",
        },
      },
    });
    out.push({pathway_id: t.pathway_id, data: res.data});
  }
  return out;
});
```

Always re-query with `fetchPolicy: "network-only"` afterward.

## Verify manager is not participant

Use the canonical Python public API helper and only return counts, not sensitive employee data:

```bash
python3 - <<'PY'
from pathlib import Path
import importlib.util, sys, json
spec=importlib.util.spec_from_file_location('gupy_educorp','gupy_educorp.py')
g=importlib.util.module_from_spec(spec); sys.modules['gupy_educorp']=g; spec.loader.exec_module(g)
api=g.PublicApi(g.parse_credentials(Path(g.DEFAULT_CREDENTIALS)))
targets={
 '45012':['LEONARDO LANGA SANTANA'],
 '44957':['GUSTAVO HENRIQUE FERNANDES','LEONARDO LANGA SANTANA','RAMON AMORIM MATOS'],
 '45018':['RAMON AMORIM MATOS'],
}
for pid,names in targets.items():
    found=[]
    for status in g.STATUSES:
        for emp in api.paginate(f'/pathways/{pid}/employees', {'status': status}, page_size=100):
            emp_name=g.normalize(emp.get('name'))
            for name in names:
                if emp_name == g.normalize(name):
                    found.append({'name': name, 'status': status})
    print(json.dumps({'pathwayId':pid,'managerParticipantCount':len(found)}, ensure_ascii=False))
PY
```

A correct result is `managerParticipantCount: 0` for every pathway.
