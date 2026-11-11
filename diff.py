"""계약서 두 버전을 조항 단위로 비교한다.

    python diff.py <v1> <v2> out/<이름>      # out/<이름>/diff.json 을 쓰고 변경 덩어리(hunk)를 보여 준다

입력은 .docx 또는 .md/.txt. `제N조(제목)` 머리로 조항을 나누고, 조 번호는 떼고 제목으로 짝을 맞춘다
(제목이 바뀌었으면 본문이 비슷한 조항끼리). 본문 안의 "제7조에 따라" 같은 참조도 옛 번호를 새 번호로 바꿔서
비교한다. 그래서 조항 하나가 끼어들어 뒤 번호가 전부 밀려도 번호만 바뀐 조항은 변경으로 잡히지 않는다.

diff.json 은 세션이 읽는 자료일 뿐이다. check.py 는 이 파일을 믿지 않고 원본 두 파일로 diff 를 다시 계산한다.
"""
import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path

HEAD = re.compile(r"^제\s*(\d+)\s*조\s*\(([^)]*)\)\s*(.*)$")
REF = re.compile(r"제\s*(\d+)\s*조")
REF_ANY = re.compile(r"제\s*\d+\s*[조항호]|^\d+\.\s")   # 숫자 검사에서 뺄 조·항·호 번호, 목록 번호
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def norm(s):
    """NFC + 공백 한 칸. 인용 대조도 같은 함수로 맞춘다."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip()


def numbers(s):
    return [n.replace(",", "") for n in NUM.findall(REF_ANY.sub(" ", s))]


def read_paragraphs(path):
    p = Path(path)
    if p.suffix.lower() == ".docx":
        from docx import Document
        lines = [para.text for para in Document(p).paragraphs]
    else:
        lines = p.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        line = norm(line.lstrip("#").strip().strip("*"))   # md 머리 기호·굵게 표시만 떼기
        if line:
            out.append(line)
    return out


def parse(paras):
    """[{no, title, head, paras}] — 첫 조항 앞 문단은 no=None 인 '전문'."""
    clauses = [{"no": None, "title": "전문", "head": "", "paras": []}]
    for t in paras:
        m = HEAD.match(t)
        if m:
            head = t[: len(t) - len(m[3])].strip() if m[3] else t
            clauses.append({"no": int(m[1]), "title": norm(m[2]), "head": head, "paras": [m[3]] if m[3] else []})
        else:
            clauses[-1]["paras"].append(t)
    return clauses


def key(title):
    return title.replace(" ", "")


def match(old, new):
    """(옛 조항, 새 조항) 짝. 제목이 같으면 짝, 남은 것끼리 본문 유사도 0.6 이상이면 짝."""
    pairs, left = [], list(new)
    for o in old:
        n = next((n for n in left if key(n["title"]) == key(o["title"])), None)
        if n:
            pairs.append((o, n))
            left.remove(n)
    lone = [o for o in old if all(o is not p[0] for p in pairs)]
    for o in lone[:]:
        best = max(left, default=None, key=lambda n: difflib.SequenceMatcher(None, " ".join(o["paras"]), " ".join(n["paras"])).ratio())
        if best and difflib.SequenceMatcher(None, " ".join(o["paras"]), " ".join(best["paras"])).ratio() >= 0.6:
            pairs.append((o, best))
            left.remove(best)
            lone.remove(o)
    return pairs, lone, left


def label(c):
    return c["title"] if c["no"] is None else f"제{c['no']}조({c['title']})"


def diff(v1, v2):
    """{hunks:[{id, clause, old, new, old_cmp}], renumbered:[…], naive_lines:int}"""
    p1, p2 = read_paragraphs(v1), read_paragraphs(v2)
    old, new = parse(p1), parse(p2)
    pairs, deleted, added = match(old, new)
    renum = {o["no"]: n["no"] for o, n in pairs if o["no"] is not None}
    remap = lambda s: REF.sub(lambda m: f"제{renum.get(int(m[1]), int(m[1]))}조", s)
    cmp_new = lambda s: REF.sub(lambda m: f"제{int(m[1])}조", s)

    hunks = []
    pos = {id(c): i for i, c in enumerate(new)}
    for o, n in sorted(pairs, key=lambda p: pos[id(p[1])]):
        if key(o["title"]) != key(n["title"]):
            hunks.append({"clause": label(n), "old": o["head"], "new": n["head"], "old_cmp": o["head"]})
        a = [remap(t) for t in o["paras"]]
        b = [cmp_new(t) for t in n["paras"]]
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag != "equal":
                hunks.append({"clause": label(n), "old": "\n".join(o["paras"][i1:i2]), "new": "\n".join(n["paras"][j1:j2]),
                              "old_cmp": "\n".join(a[i1:i2])})
    for n in added:
        hunks.append({"clause": label(n) + " 추가", "old": "", "new": "\n".join([n["head"], *n["paras"]]), "old_cmp": ""})
    for o in deleted:
        hunks.append({"clause": label(o) + " 삭제", "old": "\n".join([o["head"], *o["paras"]]), "new": "", "old_cmp": "\n".join(o["paras"])})
    for i, h in enumerate(hunks, 1):
        h["id"] = f"H{i}"
        # 숫자 비교는 참조 번호를 맞춘 쪽으로, 추가·삭제 조항은 머리(제N조) 빼고
        o_nums = numbers(h["old_cmp"])
        n_nums = numbers(h["new"])
        h["numbers_old_only"] = [x for x in o_nums if o_nums.count(x) > n_nums.count(x)]
        h["numbers_new_only"] = [x for x in n_nums if n_nums.count(x) > o_nums.count(x)]
    moved = [{"title": n["title"], "old_no": o["no"], "new_no": n["no"]} for o, n in pairs if o["no"] != n["no"]]
    naive = sum(1 for d in difflib.ndiff(p1, p2) if d[:1] in "+-")
    return {"v1": str(v1), "v2": str(v2), "hunks": hunks, "renumbered": moved, "naive_lines": naive,
            "text_old": "\n".join(p1), "text_new": "\n".join(p2)}


def changed_spans(h):
    """hunk 안에서 실제로 바뀐 글자 구간 (옛 글 쪽, 새 글 쪽)."""
    ops = difflib.SequenceMatcher(None, h["old"], h["new"], autojunk=False).get_opcodes()
    return [(i1, i2) for t, i1, i2, _, _ in ops if t != "equal"], [(j1, j2) for t, _, _, j1, j2 in ops if t != "equal"]


def main(v1, v2, out_dir):
    sys.stdout.reconfigure(encoding="utf-8")
    d = diff(v1, v2)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    view = {"v1": d["v1"], "v2": d["v2"], "renumbered": d["renumbered"],
            "hunks": [{k: h[k] for k in ("id", "clause", "old", "new", "numbers_old_only", "numbers_new_only")} for h in d["hunks"]],
            "text_new": d["text_new"]}   # 위험도 판단용 전체 맥락(누가 갑·을인지 등)
    (out / "diff.json").write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"줄 단위 diff: {d['naive_lines']}줄 → 조항 단위 변경 {len(d['hunks'])}건, 번호만 바뀐 조항 {len(d['renumbered'])}개")
    for h in d["hunks"]:
        nums = f"  [숫자 {','.join(h['numbers_old_only']) or '-'} → {','.join(h['numbers_new_only']) or '-'}]" if h["numbers_old_only"] or h["numbers_new_only"] else ""
        print(f"  {h['id']} {h['clause']}{nums}")
    print(f"→ {out / 'diff.json'}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
