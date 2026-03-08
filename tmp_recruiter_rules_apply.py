import json, pathlib, unicodedata
import jarvis


def norm(s: str) -> str:
    s = (s or "").lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s


def recruiter_for_title(title: str) -> str:
    t = norm(title)

    # rule 1: coordenador/supervisor/gerente => andre
    for kw in ["coordenador", "supervisor", "gerente"]:
        if kw in t:
            return "andre.orrico@lmmobilidade.com.br"

    # rule 2: estagiario/jovem aprendiz => gabrielly
    for kw in ["estagiario", "estágio", "estagio", "jovem aprendiz", "aprendiz"]:
        if kw in t:
            return "gabrielly.silva@lmmobilidade.com.br"

    # rule 3: everything else => larissa
    return "larissa.teixeira@lmmobilidade.com.br"


def apply(statuses=("published", "approved", "waiting_approval"), out_path="recruiter_rules_apply.json"):
    changed = []
    scanned = []

    with jarvis._gupy_client() as c:
        for status in statuses:
            page = 1
            per = 100
            while True:
                r = c.get('https://api.gupy.io/api/v1/jobs', params={'status': status, 'page': page, 'perPage': per})
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:500]}")
                data = r.json() or {}
                results = data.get('results', []) or []

                for j in results:
                    title = j.get('name') or ''
                    job_id = int(j.get('id'))
                    target = recruiter_for_title(title)

                    # robust truth: patch and read payload back
                    pr = c.patch(f'https://api.gupy.io/api/v1/jobs/{job_id}', json={'recruiterEmail': target})
                    if pr.status_code != 200:
                        changed.append({
                            'id': job_id,
                            'status': j.get('status') or status,
                            'title': title,
                            'targetRecruiterEmail': target,
                            'ok': False,
                            'error': f"HTTP {pr.status_code}: {pr.text[:800]}"
                        })
                        continue

                    jj = pr.json() if pr.text else {}
                    actual = jj.get('recruiterEmail')
                    ok = norm(actual) == norm(target)

                    row = {
                        'id': job_id,
                        'status': jj.get('status') or j.get('status') or status,
                        'title': title,
                        'targetRecruiterEmail': target,
                        'recruiterEmail': actual,
                        'recruiterName': jj.get('recruiterName'),
                        'recruiterId': jj.get('recruiterId'),
                        'updatedAt': jj.get('updatedAt'),
                        'ok': ok,
                    }
                    scanned.append(row)
                    if not ok:
                        changed.append(row)

                if len(results) < per:
                    break
                page += 1

    out = {
        'statuses': list(statuses),
        'total_scanned': len(scanned),
        'ok': sum(1 for r in scanned if r['ok']),
        'not_ok': sum(1 for r in scanned if not r['ok']),
        'rows': scanned,
        'errors': [r for r in changed if not r.get('ok')],
    }
    pathlib.Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    return out


def main():
    out = apply()
    print(json.dumps({k: out[k] for k in ['total_scanned', 'ok', 'not_ok']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
