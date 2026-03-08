import asyncio, unicodedata, json

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


async def main():
    all_jobs = []
    # status values: "published", "approved" and (equivalente a "in approval") = "waiting_approval"
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
                    all_jobs.append(
                        {
                            "id": j.get("id"),
                            "status": j.get("status"),
                            "name": j.get("name"),
                            "createdAt": j.get("createdAt"),
                            "recruiterEmail": j.get("recruiterEmail"),
                            "recruiterName": j.get("recruiterName"),
                            "recruiterId": j.get("recruiterId"),
                        }
                    )
                if len(results) < per:
                    break
                page += 1

    andre_email = "andre.orrico@lmmobilidade.com.br"
    matched = []
    for j in all_jobs:
        if not match_andre(j.get("name") or ""):
            continue
        cur_email = j.get("recruiterEmail") or ""
        action = "ok" if norm(cur_email) == norm(andre_email) else "mudar"
        matched.append(
            {
                "id": j.get("id"),
                "status": j.get("status"),
                "title": j.get("name"),
                "createdAt": j.get("createdAt"),
                "recruiterEmail": j.get("recruiterEmail"),
                "recruiterName": j.get("recruiterName"),
                "action": action,
            }
        )

    matched.sort(key=lambda x: (x["action"] != "mudar", x["status"] or "", x["title"] or ""))

    out = {
        "total_jobs": len(all_jobs),
        "andre_matched": len(matched),
        "to_change": sum(1 for r in matched if r["action"] == "mudar"),
        "rows": matched,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
