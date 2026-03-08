import asyncio
import json
import time

import jarvis

ANDRE_EMAIL = "andre.orrico@lmmobilidade.com.br"


def load_rows(path: str):
    raw = open(path, "r", encoding="utf-8").read()
    # jarvis prints a banner line on import; strip if leaked into file
    if raw.startswith("✅"):
        raw = "\n".join(raw.splitlines()[1:])
    return json.loads(raw)


async def main():
    inv = load_rows("andre_inventory.json")
    rows = [r for r in inv.get("rows", []) if r.get("action") == "mudar"]
    print(f"to_change={len(rows)}")

    ok = 0
    fail = 0
    results = []
    for i, r in enumerate(rows, 1):
        job_id = int(r["id"])
        tr = await jarvis.gupy_v1_set_recruiter.run({"job_id": job_id, "recruiter_email": ANDRE_EMAIL})
        # ToolResult content is list[TextContent]
        txt = tr.structured_content.get("result") if getattr(tr, "structured_content", None) else None
        if not txt:
            txt = "\n".join([c.text for c in getattr(tr, "content", []) if hasattr(c, "text")])
        success = (txt or "").strip().lower().startswith("ok:")
        if success:
            ok += 1
        else:
            fail += 1
        results.append({"job_id": job_id, "status": r.get("status"), "title": r.get("title"), "result": txt, "success": success})
        print(f"[{i}/{len(rows)}] {job_id}: {'OK' if success else 'FAIL'}")
        time.sleep(0.25)

    out = {"andre_email": ANDRE_EMAIL, "attempted": len(rows), "ok": ok, "fail": fail, "results": results}
    open("andre_apply_results.json", "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=2))
    print("written andre_apply_results.json")


if __name__ == "__main__":
    asyncio.run(main())
