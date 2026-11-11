"""요약 세션이 끝난 뒤 사람이 돌리는 최종 확인. 작업 폴더의 검사기와 예시 계약서는 믿지 않는다.

    python verify.py <믿는 커밋> <v1> <v2> out/<이름>
    예: python verify.py 1a2b3c4 samples/용역계약_v1.docx samples/용역계약_v2.docx out/용역계약

1. 이 저장소를 임시 폴더에 새로 받아 <믿는 커밋>을 꺼낸다(작업 폴더의 git 훅·설정은 타지 않는다).
2. 작업 폴더 파일(out/ 말고 전부: diff.py·check.py·samples/·.claude/ …)이 그 커밋과 다르거나 새 파일이 있으면 실패.
3. summary.json 한 파일만 깨끗한 사본으로 옮겨, 그쪽 test_check.py 와 check.py 로 다시 검사한다.
   계약서가 저장소 안(samples/ 등)이면 깨끗한 사본 쪽 파일로 검사한다. 저장소 밖 계약서는 받은 그대로 쓴다.
4. 입력·결과 경로에 심볼릭 링크나 정션이 끼어 있으면 멈춘다(다른 폴더를 원본처럼 보이게 할 수 있다).

<믿는 커밋>은 세션이 바꿀 수 없는 곳에서 가져온다: 내가 적어 둔 해시, 또는 GitHub 에 올린 뒤라면 원격의 해시.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKIP = {".git", "out", "__pycache__"}


def run(*cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8")


def no_links(p: Path):
    """p 자신, 그리고 저장소 안이면 저장소까지의 위 폴더에 링크·정션이 있으면 멈춘다(경로는 abspath, 링크 안 따라감)."""
    for q in [p, *p.parents]:
        if q == HERE:
            break
        if q.is_symlink() or q.is_junction():
            sys.exit(f"✗ {q} 가 링크다(다른 파일을 원본처럼 보이게 할 수 있다) — 멈춘다")
        if HERE not in q.parents:
            break   # 저장소 밖 계약서는 파일 자신만 본다


def main(commit, v1, v2, out_dir):
    sys.stdout.reconfigure(encoding="utf-8")
    paths = [Path(os.path.abspath(p)) for p in (v1, v2, out_dir)]
    out = paths[2]
    for p in [*paths, out / "summary.json"]:
        no_links(p)
    if not out.is_relative_to(HERE / "out"):
        sys.exit("✗ 결과 폴더는 이 저장소의 out/ 안이어야 한다")
    with tempfile.TemporaryDirectory() as tmp:
        clean = Path(tmp) / "repo"
        r = run("git", "-c", "core.hooksPath=", "clone", "-q", "--no-hardlinks", "--no-checkout", str(HERE), str(clean), cwd=tmp)
        r = r.returncode == 0 and run("git", "-c", "core.hooksPath=", "checkout", "-q", commit, cwd=clean)
        if not r or r.returncode:
            sys.exit(f"✗ 커밋 {commit} 을 꺼내지 못했다")
        tracked = set(run("git", "-c", "core.quotepath=false", "ls-files", cwd=clean).stdout.splitlines())
        changed = []
        for p in HERE.rglob("*"):
            rel = p.relative_to(HERE).as_posix()
            if p.is_dir() or rel.split("/")[0] in SKIP or "__pycache__" in rel:
                continue
            if rel not in tracked:
                changed.append(f"{rel} (새 파일)")
            elif p.read_bytes().replace(b"\r\n", b"\n") != (clean / rel).read_bytes().replace(b"\r\n", b"\n"):
                changed.append(rel)
        changed += [f"{t} (지워짐)" for t in tracked if t.split("/")[0] not in SKIP and not (HERE / t).exists()]
        for c in changed:
            print("✗ 믿는 커밋과 다르다:", c, flush=True)
        # 저장소 안 계약서는 깨끗한 사본 쪽을 쓴다 — 세션이 원본을 바꿔 지어낸 인용을 "원문에 있게" 만들 수 있어서
        ins = [str(clean / p.relative_to(HERE)) if p.is_relative_to(HERE) else str(p) for p in paths[:2]]
        dst = clean / "out" / out.name
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out / "summary.json", dst / "summary.json")
        py = [sys.executable, "-E"]   # PYTHONPATH 같은 환경변수로 끼어드는 코드를 막는다
        ok = subprocess.run([*py, "test_check.py"], cwd=clean).returncode == 0
        ok = subprocess.run([*py, "check.py", *ins, f"out/{out.name}"], cwd=clean).returncode == 0 and ok
        if ok:
            fd, t = tempfile.mkstemp(dir=out)   # 링크를 따라 밖에 쓰지 않게 같은 폴더 임시 파일 → 이름 바꿔 끼우기
            os.close(fd)
            shutil.copyfile(dst / "변경점.md", t)
            os.replace(t, out / "변경점.md")
    if changed:
        print("✗ 요약 세션이 out/ 밖을 바꿨다 — 요약이 통과해도 실패")
    return 0 if ok and not changed else 1


if __name__ == "__main__":
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    sys.exit(main(*sys.argv[1:]))
