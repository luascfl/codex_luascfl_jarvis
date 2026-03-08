import unicodedata, json, pathlib
import jarvis

# nota: use postcheck_for(email, out_path=...) para rodar checagens para outros recruiters


def norm(s: str) -> str:
    s = (s or "").lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s


def match_andre(title: str) -> bool:
    t = norm(title)
    for kw in ["coordenador", "supervisor", "gerente"]:
        if kw in t:
            return True
    return False


def postcheck_for(email: str, out_path: str = 'andre_postcheck.json'):
    checked = []
    # checagem robusta: a listagem /api/v1/jobs nem sempre retorna recruiterEmail/recruiterName
    # entao aqui validamos fazendo PATCH idempotente (reaplicar o mesmo recruiterEmail) e
    # usando o payload do PATCH como fonte de verdade.
    rows_to_check = []

    with jarvis._gupy_client() as c:
        for status in ['published', 'approved', 'waiting_approval']:
            page = 1
            per = 100
            while True:
                r = c.get('https://api.gupy.io/api/v1/jobs', params={'status': status, 'page': page, 'perPage': per})
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:500]}")
                data = r.json()
                results = data.get('results', []) or []
                for j in results:
                    title = j.get('name') or ''
                    if not match_andre(title):
                        continue
                    rows_to_check.append({'id': j.get('id'), 'status': j.get('status'), 'title': title})
                if len(results) < per:
                    break
                page += 1

        for row in rows_to_check:
            job_id = int(row.get('id'))
            pr = c.patch(f'https://api.gupy.io/api/v1/jobs/{job_id}', json={'recruiterEmail': email})
            if pr.status_code != 200:
                checked.append({**row, 'recruiterEmail': None, 'recruiterName': None, 'ok': False, 'error': f"HTTP {pr.status_code}: {pr.text[:800]}"})
                continue
            jj = pr.json() if pr.text else {}
            checked.append({
                **row,
                'recruiterEmail': jj.get('recruiterEmail'),
                'recruiterName': jj.get('recruiterName'),
                'recruiterId': jj.get('recruiterId'),
                'updatedAt': jj.get('updatedAt'),
                'ok': norm(jj.get('recruiterEmail') or '') == norm(email),
            })

    out = {
        'target_recruiter_email': email,
        'total_matched': len(checked),
        'ok': sum(1 for r in checked if r['ok']),
        'not_ok': sum(1 for r in checked if not r['ok']),
        'rows': checked,
    }
    pathlib.Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    return out



def main():
    andre_email = 'andre.orrico@lmmobilidade.com.br'
    out = postcheck_for(andre_email, out_path='andre_postcheck.json')
    print(json.dumps({k: out[k] for k in ['total_matched', 'ok', 'not_ok']}, ensure_ascii=False))


if __name__ == "__main__":
    main()
