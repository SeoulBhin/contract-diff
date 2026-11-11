"""세션이 쓴 summary.json 을 원문과 대조하고 변경점 보고서(변경점.md)를 만든다.

    python check.py <v1> <v2> out/<이름>

diff 는 out/ 의 diff.json 을 쓰지 않고 원본 두 파일로 다시 계산한다(세션이 diff.json 을 고칠 수 있어서).

오류(종료 코드 1, 보고서 안 만듦) — summary.json 을 고쳐서 다시 돌린다
  - 인용(before/after)이 그 변경 덩어리(hunk)의 원문에 없다, 또는 있어도 안 바뀐 부분만 인용했다
  - 요약 문장에 인용에 없는 숫자가 있다
  - 숫자가 바뀐 hunk 를 "표현만 바뀜"에 넣었다 / 그 hunk 를 다룬 항목 인용에 바뀐 숫자가 없다
  - 없는 hunk 번호, 위험도 값, 칸 빠짐
미검토(오류 아님) — 어디에도 안 들어간 hunk 는 보고서 맨 위에 원문 그대로 올린다
"""
import json
import sys
from pathlib import Path

from diff import changed_spans, diff, norm, numbers

RISKS = ("높음", "중간", "낮음")


def overlaps(text, quote, spans):
    """quote 가 text 안에 있고, 그 위치가 바뀐 구간과 겹치는가. (있음, 겹침)"""
    start = text.find(quote)
    found = start >= 0
    while start >= 0:
        end = start + len(quote)
        if any((a < end and b > start) or (a == b and start <= a <= end) for a, b in spans):
            return True, True
        start = text.find(quote, start + 1)
    return found, False


def review(d, s):
    """(errors, items, wording, unreviewed). s = summary.json 내용."""
    hunks = {h["id"]: h for h in d["hunks"]}
    errors = []
    if not isinstance(s, dict) or not isinstance(s.get("items"), list) or not isinstance(s.get("wording_only"), list):
        return ['summary.json 은 {"items": [...], "wording_only": [...]} 꼴이어야 한다'], [], [], []
    covered, quoted = {}, {}
    for n, it in enumerate(s["items"], 1):
        tag = f"항목 {n}"
        if not isinstance(it, dict):
            errors.append(f"{tag}: 객체가 아니다")
            continue
        ids = it.get("hunks")
        if not (isinstance(ids, list) and ids and all(i in hunks for i in ids)):
            errors.append(f"{tag}: hunks 는 있는 hunk 번호 목록이어야 한다: {ids!r}")
            continue
        if it.get("risk") not in RISKS:
            errors.append(f"{tag}: risk 는 {'/'.join(RISKS)} 중 하나: {it.get('risk')!r}")
        if not str(it.get("summary") or "").strip():
            errors.append(f"{tag}: summary 가 비었다")
        q = {}
        for side, txt in (("before", "old"), ("after", "new")):
            v = it.get(side)
            if v is None:
                if any(hunks[i][txt] for i in ids):
                    errors.append(f"{tag}: {side} 가 null 인데 {'옛' if txt == 'old' else '새'} 글이 있는 hunk 다")
                continue
            if not isinstance(v, str) or not norm(v):
                errors.append(f"{tag}: {side} 는 원문 문자열 또는 null")
                continue
            v = norm(v)
            q[side] = v
            hit = [overlaps(hunks[i][txt], v, changed_spans(hunks[i])[0 if txt == "old" else 1]) for i in ids]
            if not any(f for f, _ in hit):
                where = "v1" if txt == "old" else "v2"
                elsewhere = v in norm(d["text_old" if txt == "old" else "text_new"].replace("\n", " "))
                errors.append(f"{tag}: {side} 인용이 {'/'.join(ids)} 원문에 없다" + (f"({where} 다른 곳에는 있다)" if elsewhere else f"({where} 어디에도 없다)") + f": {v[:60]!r}")
            elif not any(o for _, o in hit):
                errors.append(f"{tag}: {side} 인용이 바뀐 부분이 아니다(안 바뀐 문장): {v[:60]!r}")
        if not q:
            errors.append(f"{tag}: before·after 둘 다 비었다")
        allowed = set(numbers(" ".join(q.values())))
        extra = [x for x in numbers(str(it.get("summary") or "")) if x not in allowed]
        if extra:
            errors.append(f"{tag}: 요약 문장의 숫자 {', '.join(extra)} 가 인용에 없다(원문에서 인용하거나 숫자를 빼라)")
        for i in ids:
            covered.setdefault(i, []).append(n)
            quoted.setdefault(i, {"before": "", "after": ""})
            for side in q:
                quoted[i][side] += " " + q[side]
    wording = []
    for w in s["wording_only"]:
        i = w.get("hunk") if isinstance(w, dict) else None
        if i not in hunks:
            errors.append(f"표현만 바뀜: 없는 hunk 번호 {i!r}")
            continue
        h = hunks[i]
        if h["numbers_old_only"] or h["numbers_new_only"]:
            errors.append(f"표현만 바뀜: {i} 는 숫자가 바뀌었다({','.join(h['numbers_old_only']) or '-'} → {','.join(h['numbers_new_only']) or '-'}) — 변경 항목으로 써야 한다")
        if not h["old"] or not h["new"]:
            errors.append(f"표현만 바뀜: {i} 는 조항 추가·삭제다 — 변경 항목으로 써야 한다")
        if i in covered:
            errors.append(f"표현만 바뀜: {i} 는 변경 항목 {covered[i]} 에도 있다 — 한쪽만")
        wording.append((h, str(w.get("why") or "")))
    for i, qs in quoted.items():
        h = hunks[i]
        miss = [x for x in h["numbers_old_only"] if x not in numbers(qs["before"])] + \
               [x for x in h["numbers_new_only"] if x not in numbers(qs["after"])]
        if miss:
            errors.append(f"{i}: 바뀐 숫자 {', '.join(sorted(set(miss)))} 가 항목 인용에 없다 — 숫자가 바뀐 문장을 인용해야 한다")
    done = set(covered) | {h["id"] for h, _ in wording}
    unreviewed = [h for h in d["hunks"] if h["id"] not in done]
    return errors, s["items"], wording, unreviewed


def block(h):
    return f"- 전: {h['old'] or '(없음)'}\n- 후: {h['new'] or '(없음)'}".replace("\n", "\n  ")


def report(d, items, wording, unreviewed):
    hunks = {h["id"]: h for h in d["hunks"]}
    cnt = {r: sum(1 for it in items if it["risk"] == r) for r in RISKS}
    L = [f"# 변경점: {Path(d['v1']).name} → {Path(d['v2']).name}", "",
         f"미검토 {len(unreviewed)}건 · 변경 항목 {len(items)}건(높음 {cnt['높음']} / 중간 {cnt['중간']} / 낮음 {cnt['낮음']}) · "
         f"표현만 바뀜 {len(wording)}건 · 번호만 바뀐 조항 {len(d['renumbered'])}개", ""]
    if unreviewed:
        L += ["## 미검토 — 요약에 없는 변경, 직접 읽어야 한다", ""]
        for h in unreviewed:
            L += [f"### {h['id']} {h['clause']}", block(h), ""]
    L += ["## 변경 항목", ""]
    for it in sorted(items, key=lambda it: RISKS.index(it["risk"])):
        L += [f"### [{it['risk']}] {' · '.join(hunks[i]['clause'] for i in it['hunks'])} ({', '.join(it['hunks'])})", "",
              it["summary"].strip(), "", f"- 전: {it.get('before') or '(없음)'}", f"- 후: {it.get('after') or '(없음)'}", ""]
    if wording:
        L += ["## 표현만 바뀜 — 원문 그대로 둔다, 뜻이 바뀌지 않았는지 눈으로 확인", ""]
        for h, why in wording:
            L += [f"### {h['id']} {h['clause']}: {why}", block(h), ""]
    if d["renumbered"]:
        L += ["## 번호만 바뀐 조항 (내용 같음)", ""]
        L += [f"- {m['title']}: 제{m['old_no']}조 → 제{m['new_no']}조" for m in d["renumbered"]] + [""]
    return "\n".join(L)


def main(v1, v2, out_dir):
    sys.stdout.reconfigure(encoding="utf-8")
    out = Path(out_dir)
    d = diff(v1, v2)
    try:
        s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"  ✗ summary.json 을 읽지 못했다: {e}")
        return 1
    errors, items, wording, unreviewed = review(d, s)
    if errors:
        for e in errors:
            print("  ✗", e)
        print(f"오류 {len(errors)}건 — summary.json 을 고치고 다시 돌린다 (보고서는 만들지 않았다)")
        return 1
    (out / "변경점.md").write_text(report(d, items, wording, unreviewed), encoding="utf-8")
    print(f"{out / '변경점.md'}  (변경 항목 {len(items)}건 / 표현만 바뀜 {len(wording)}건 / 미검토 {len(unreviewed)}건)")
    for h in unreviewed:
        print(f"  ? 미검토 {h['id']} {h['clause']}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    sys.exit(main(*sys.argv[1:]))
