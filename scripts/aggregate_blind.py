"""블라인드 채점 결과를 문항당 3회 다수결로 모아 버전 비교.

A~F 라벨을 key.json으로 (run, rep)에 되돌리고, 같은 run의 3회 등급을 다수결로 정한다.
O 2개 이상 → O, △ 2개 이상 → △, X 2개 이상 → X, 셋 다 다르면 △.

사용법: python scripts/aggregate_blind.py <blind 폴더>
"""
import json
import collections
import sys

S = sys.argv[1] if len(sys.argv) > 1 else "."
key = json.load(open(f"{S}/key.json"))
G = {}
for p in ["p1", "p2", "p3", "p4"]:
    G.update(json.load(open(f"{S}/{p}.grades.json")))

cell = collections.defaultdict(dict)
verbose = collections.defaultdict(int)
for qid, labs in G.items():
    for lab, v in labs.items():
        run, rep = key[qid][lab].split(":")
        cell[(qid, run)][rep] = v[0]
        if v[1] == "Y":
            verbose[run] += 1


def maj(d):
    c = collections.Counter(d.values())
    if c.get("O", 0) >= 2:
        return "O"
    if c.get("△", 0) >= 2:
        return "△"
    if c.get("X", 0) >= 2:
        return "X"
    return "△"


sets = {
    "Q": [f"Q{i:02d}" for i in range(1, 33)],
    "H": [f"H{i:02d}" for i in range(1, 11)],
    "J": [f"J{i:02d}" for i in range(1, 11)],
    "K": [f"K{i:02d}" for i in range(1, 11)],
}
rm = {
    "Q": ("v1.3", "v1.4"),
    "H": ("v1.3-holdout", "v1.4-holdout"),
    "J": ("v1.3-holdout2", "v1.4-holdout2"),
    "K": ("v1.3-holdout3", "v1.4-holdout3"),
}
final = {}
for tag, ids in sets.items():
    for run in rm[tag]:
        cnt = collections.Counter()
        for qid in ids:
            g = maj(cell[(qid, run)])
            final[(qid, run)] = g
            cnt[g] += 1
        print(f"{run:16} O {cnt['O']:2}  △ {cnt[chr(0x25b3)]:2}  X {cnt['X']:2}  (verbose {verbose[run]})")
print("\nper-question 1.3 -> 1.4:")
for tag, ids in sets.items():
    r13, r14 = rm[tag]
    diffs = [(q, final[(q, r13)], final[(q, r14)]) for q in ids if final[(q, r13)] != final[(q, r14)]]
    print(f" [{tag}]", " | ".join(f"{q} {a}->{b}" for q, a, b in diffs) or "none")
json.dump({f"{q}|{r}": g for (q, r), g in final.items()}, open(f"{S}/final.json", "w"), ensure_ascii=False)
spread = sum(1 for k, d in cell.items() if len(set(d.values())) > 1)
print(f"\ninstability: {spread}/{len(cell)} (run,q) split across 3 reps")
