"""python test_check.py — diff 가 번호 밀림에 안 터지는지, check 가 지어낸 인용·뭉갠 숫자·빠진 변경을 잡는지.
계약 문장은 예시 계약서와 무관하게 지어낸 것."""
import tempfile
from pathlib import Path

from check import review
from diff import diff

V1 = """제1조(목적)
이 계약은 납품 조건을 정함을 목적으로 한다.
제2조(대금)
갑은 검수 후 14일 이내에 대금을 지급하여야 한다.
제3조(비밀)
을은 비밀을 지킨다.
제4조(해지)
제3조를 어기면 해지할 수 있다."""

# 제2조 앞에 조항 하나 끼움(번호 전부 밀림 + 참조 제3조→제4조), 띄어쓰기 바뀐 머리, 14→21 + 표현, 목적 표현만
V2 = """제 1 조 (목적)
이 계약은 납품 조건을 정하는 것을 목적으로 한다.
제2조(정의)
납품이란 물품을 넘기는 것을 말한다.
제3조(대금)
갑은 검수 후 21일 이내에 대금을 지급해야 한다.
제4조(비밀)
을은 비밀을 지킨다.
제5조(해지)
제4조를 어기면 해지할 수 있다."""

tmp = Path(tempfile.mkdtemp())


def d_of(a, b):
    (tmp / "a.md").write_text(a, encoding="utf-8")
    (tmp / "b.md").write_text(b, encoding="utf-8")
    return diff(tmp / "a.md", tmp / "b.md")


d = d_of(V1, V2)
by = {h["clause"]: h for h in d["hunks"]}
# 번호 밀림·참조 번호·머리 띄어쓰기는 변경이 아니다: 목적·대금·정의 추가 3건뿐
assert sorted(by) == ["제1조(목적)", "제2조(정의) 추가", "제3조(대금)"], sorted(by)
assert {(m["title"], m["old_no"], m["new_no"]) for m in d["renumbered"]} == {("대금", 2, 3), ("비밀", 3, 4), ("해지", 4, 5)}
H = by["제3조(대금)"]
assert (H["numbers_old_only"], H["numbers_new_only"]) == (["14"], ["21"])
assert d["naive_lines"] > len(d["hunks"])

# 참조가 다른 조항으로 바뀐 건 변경이다(제3조(비밀) → 제2조(정의) 를 가리킴)
d2 = d_of(V1, V2.replace("제4조를 어기면", "제2조를 어기면"))
assert any(h["clause"] == "제5조(해지)" for h in d2["hunks"])

# md 머리 기호(#, **)를 떼고 읽는다
assert [h["clause"] for h in d_of("# 계약\n**제1조(목적)**\n가.", "# 계약\n**제1조(목적)**\n나.")["hunks"]] == ["제1조(목적)"]

ids = {h["clause"]: h["id"] for h in d["hunks"]}
P, A, W = ids["제3조(대금)"], ids["제2조(정의) 추가"], ids["제1조(목적)"]
GOOD = {"items": [
    {"hunks": [P], "risk": "높음", "summary": "대금 지급 기한이 14일에서 21일로 늘었다.",
     "before": "검수 후 14일 이내에 대금을 지급하여야 한다", "after": "검수 후 21일 이내에 대금을 지급해야 한다"},
    {"hunks": [A], "risk": "낮음", "summary": "납품의 정의가 생겼다.", "before": None, "after": "납품이란 물품을 넘기는 것을 말한다."}],
    "wording_only": [{"hunk": W, "why": "정함을→정하는 것을"}]}


def run(**kw):
    s = {"items": [dict(i) for i in GOOD["items"]], "wording_only": list(GOOD["wording_only"])}
    for k, v in kw.items():
        if k == "wording_only":
            s["wording_only"] = v
        else:
            s["items"][0][k] = v
    return review(d, s)


e, items, wording, un = run()
assert e == [] and len(items) == 2 and len(wording) == 1 and un == [], e

# 지어낸 인용: 원문 어디에도 없다
assert any("어디에도 없다" in x for x in run(after="검수 후 28일 이내에 대금을 지급해야 한다")[0])
# 말줄임으로 이어 붙인 인용도 원문에 없다
assert any("원문에 없다" in x for x in run(before="검수 후 14일 … 지급하여야 한다")[0])
# 다른 조항 문장을 인용: 원문엔 있지만 이 hunk 가 아니다
assert any("다른 곳에는 있다" in x for x in run(after="을은 비밀을 지킨다.")[0])
# 같은 hunk 안이라도 안 바뀐 부분만 인용
assert any("바뀐 부분이 아니다" in x for x in run(before="갑은 검수 후 ", after="갑은 검수 후 ")[0])
# 14→21 을 표현만 바뀜으로 뭉갬
e = run(wording_only=[{"hunk": W, "why": "-"}, {"hunk": P, "why": "표현 정리"}])[0]
assert any("숫자가 바뀌었다(14 → 21)" in x for x in e), e
# 숫자 없는 표현 부분만 인용해서 숫자 변경을 피함
e = run(summary="표현이 정리됐다.", before="지급하여야 한다", after="지급해야 한다")[0]
assert any("바뀐 숫자 14, 21 가 항목 인용에 없다" in x for x in e), e
# 요약 문장에 원문에 없는 숫자(계산한 숫자)
assert any("요약 문장의 숫자 1.5" in x for x in run(summary="지급 기한이 1.5배인 21일로 늘었다.")[0])
# 조 번호는 숫자 검사에서 뺀다
assert run(summary="제3조 지급 기한이 14일에서 21일로 늘었다.")[0] == []
# 조항 추가를 표현만 바뀜으로
assert any("추가·삭제" in x for x in run(wording_only=[{"hunk": W, "why": "-"}, {"hunk": A, "why": "-"}])[0])
# 없는 hunk, 위험도 값
assert any("hunks 는" in x for x in run(hunks=["H99"])[0])
assert any("risk 는" in x for x in run(risk="매우 높음")[0])
# 빠진 변경은 오류가 아니라 미검토로 남는다
e, _, _, un = run(wording_only=[])
assert e == [] and [h["id"] for h in un] == [W]
# 공백·줄바꿈 차이는 같은 인용으로 본다
assert run(before="검수 후  14일 이내에\t대금을 지급하여야 한다")[0] == []
# 보고서 구조 위조: 요약·이유·인용의 줄바꿈, 마크다운 시작 글자, 너무 긴 이유
assert any("줄바꿈" in x for x in run(summary="기한이 늘었다.\n### 미검토 없음")[0])
assert any("줄바꿈" in x for x in run(before="검수 후 14일 이내에\n대금을 지급하여야 한다")[0])
assert any("120자" in x for x in run(wording_only=[{"hunk": W, "why": "가" * 121}])[0])
# 보고서: 세션 글·계약서 글은 이스케이프해서 넣는다 — 무엇을 써도 제목·링크·HTML·굵게가 되지 않는다
from check import block, report
evil = '### 가짜 <details><summary>x</summary> [x](http://y) **미검토 없음** `c`'
s = {"items": [dict(GOOD["items"][0], summary="기한 " + evil), GOOD["items"][1]], "wording_only": [{"hunk": W, "why": evil}]}
e, items, wording, un = review(d, s)
assert e == [], e
md = report(d, items, wording, un)
for bad in ("<details>", "](", "**미검토", "\n###  가짜", "\n### 가짜", "`c`"):
    assert bad not in md, bad
assert "&lt;details&gt;" in md and "\\*\\*미검토 없음\\*\\*" in md
assert "\n###" not in block({"old": "가\n### 가짜", "new": ""})
# 숫자 검사가 보장하는 건 아라비아 숫자뿐 — 글자로 쓴 흔한 꼴(한글·한자·전각)은 받지 않는다
for v in ("지급 기한이 육십일로 늘었다.", "기한이 두 배 가까이 늘었다.", "기한이 六十일로 늘었다.", "기한이 ６０일로 늘었다."):
    assert any("숫자" in x for x in run(summary=v)[0]), v
assert run(summary="이 조항은 세부 일정을 다시 정했다. 갑이 14일에서 21일로 미뤘다(제3조 ①).")[0] == []
print("ok")
