import unicodedata, json
import jarvis


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


def main():
    andre_email = "andre.orrico@lmmobilidade.com.br"
    checked = []

    with jarvis._gupy_client() as c:
        for status in ["published", "approved", "waiting_approval"]:
            page = 1
            per = 100
            while True:
                r = c.get(
                    "https://api.gupy.io/api/v1/jobs",
                    params={"status": status, "page": page, "perPage": per},
                )
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:500]}")
                data = r.json()
                results = data.get("results", []) or []
                for j in results:
                    title = j.get("name") or ""
                    if not match_andre(title):
                        continue
                    checked.append(
                        {
                            "id": j.get("id"),
                            "status": j.get("status"),
                            "title": title,
                            "recruiterEmail": j.get("recruiterEmail"),
                            "recruiterName": j.get("recruiterName"),
                            "ok": norm(j.get("recruiterEmail") or "") == norm(andre_email),
                        }
                    )
                if len(results) < per:
                    break
                page += 1

    out = {
        "andre_email": andre_email,
        "total_matched": len(checked),
        "ok": sum(1 for r in checked if r["ok"]),
        "not_ok": sum(1 for r in checked if not r["ok"]),
        "rows": checked,
    }
    open("andre_postcheck.json", "w", encoding="utf-8").write(
        json.dumps(out, ensure_ascii=False, indent=2)
    )
    print(json.dumps({k: out[k] for k in ["total_matched", "ok", "not_ok"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
