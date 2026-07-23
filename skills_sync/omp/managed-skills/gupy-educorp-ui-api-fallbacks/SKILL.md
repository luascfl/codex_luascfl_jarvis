---
name: gupy-educorp-ui-api-fallbacks
description: "Use when Gupy EduCorp admin UI search modals fail but an authenticated browser session exists, to add participants or managers through the same session-backed endpoints without exposing secrets."
---

# Gupy EduCorp admin UI API fallbacks

Use this when the Gupy EduCorp admin UI is logged in but a modal search or click flow fails, especially participants or managers on pathway edit pages.

## Rules

- Never print Firebase access tokens, refresh tokens, CPFs, e-mails, or bulk payloads in chat.
- Prefer the canonical UI flow first. Use this fallback only when the modal search is visibly broken, returns only groups, or cannot focus/type reliably.
- Run inside `xd://browser` on the authenticated Gupy tab, so the session token is read in page context and never leaves the browser automation cell output.
- Sanitize outputs: counts, HTTP status, names already requested by the user, role, and verification status are enough.

## Get Firebase access token inside the page

```js
async function getFirebaseAccessToken() {
  const req = indexedDB.open('firebaseLocalStorageDb');
  const db = await new Promise((resolve, reject) => {
    req.onerror = () => reject(req.error);
    req.onsuccess = () => resolve(req.result);
  });
  const tx = db.transaction('firebaseLocalStorage', 'readonly');
  const all = tx.objectStore('firebaseLocalStorage').getAll();
  const rows = await new Promise((resolve, reject) => {
    all.onerror = () => reject(all.error);
    all.onsuccess = () => resolve(all.result);
  });
  return rows[0].value.stsTokenManager.accessToken;
}
```

## Search employees/accounts by name

Use raw token for `auth.api.niduu.com`.

```js
const token = await getFirebaseAccessToken();
const company = 5859;
const deviceId = localStorage.getItem('deviceId') || 'browser';
const authHeaders = {
  Authorization: token,
  'app-name': 'admin',
  'tz-offset': String(new Date().getTimezoneOffset()),
  'device-id': deviceId,
};

const resp = await fetch(
  `https://auth.api.niduu.com/admin/employments/?company=${company}&pagination=pageNumber&page=1&q=${encodeURIComponent(name)}`,
  { headers: authHeaders },
);
const data = await resp.json();
```

Pick exact normalized `account.registered_name || account.name || account.firebase_name` when possible.

## Add standalone participants to a pathway

Use bearer token for `pathways-core.niduu.com`.

```js
const coreHeaders = {
  Authorization: `Bearer ${token}`,
  'app-name': 'admin',
  'tz-offset': String(new Date().getTimezoneOffset()),
  'device-id': deviceId,
  'content-type': 'application/json',
};

const users = foundAccounts.map((account) => ({
  uid: account.uid,
  name: account.registered_name || account.name || account.firebase_name,
  nin: account.nin,
  email: account.email,
  photoUrl: account.photo_url,
  firebaseName: account.firebase_name,
}));

const post = await fetch(
  `https://pathways-core.niduu.com/v1/pathways/${pathwayId}/participants:batchCreate?company=${company}`,
  { method: 'POST', headers: coreHeaders, body: JSON.stringify({ users }) },
);
```

Verify with:

```js
const verify = await fetch(
  `https://pathways-core.niduu.com/v1/pathways/${pathwayId}/standaloneEnrollments?company=${company}&pagination=pageNumber&page=1&maxPageSize=100`,
  { headers: coreHeaders },
);
```

## Add a manager to a pathway

Search the account first, then post role `MANAGER`.

```js
const post = await fetch(
  `https://pathways-core.niduu.com/v1/pathways/${pathwayId}/managers/?company=${company}`,
  {
    method: 'POST',
    headers: coreHeaders,
    body: JSON.stringify({ uid: account.uid, role: 'MANAGER' }),
  },
);
```

Verify with:

```js
const verify = await fetch(
  `https://pathways-core.niduu.com/v1/pathways/${pathwayId}/managers?company=${company}&pathwayId=${pathwayId}&maxPageSize=100&pageToken=MQ==`,
  { headers: coreHeaders },
);
```

## Evidence files

Save sanitized JSON beside the request folder, for example:

- `automacao_participantes_api_resultado.json`
- `automacao_gestor_api_resultado.json`
- `automacao_<slug>_resultado_final.json`

Recommended fields: `foundCount`, `notFound`, `post.status`, `post.ok`, `verifyStatus`, `verifyCount`, names verified, manager role, and pathway URL. Do not save tokens or raw CPF/e-mail lists in these evidence files.
