"""Quality and stability statistics for the deontic extractor against the silver sets.

Quality: agreement of each prediction run with silver v1 (held-out, few-shot
articles excluded) and silver v2 (stratified sample), with Cohen's kappa,
bootstrap intervals, a stratum-weighted estimate for v2, a clean vs flagged
split, per-tag precision/recall and a pooled confusion matrix.

Stability: how consistent the runs are with each other on all articles
(per-article flip rate, Fleiss' kappa, pairwise Cohen's kappa), whether the
majority vote over runs scores better than single runs, and whether unstable
articles are wrong more often.

Usage (from prototype/):
    python scripts/silver_stats.py
    python scripts/silver_stats.py --runs runs/gpt4o_raw.csv runs/gpt4o_heldout.csv
"""
import argparse
import csv
import glob
import math
import random
import statistics
from collections import Counter, defaultdict

TAGS = ["obligation", "prohibition", "permission", "exemption", "constitutive"]
FEWSHOT = {"1.1", "22.26", "22.27", "22.28"}


def label(row):
    """Collapse a row to one label: the deontic tag, or 'constitutive'."""
    return row.get("deontic") or row.get("statement_type") or "none"


def read_csv(path):
    """Read a CSV keyed by article nummer."""
    with open(path, encoding="utf-8") as f:
        return {r["nummer"]: r for r in csv.DictReader(f)}


def cohen_kappa(a, b):
    """Cohen's kappa for two equal-length label lists."""
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[t] * cb[t] for t in set(a) | set(b)) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def fleiss_kappa(table):
    """Fleiss' kappa.

    Args:
        table: One Counter per item, mapping label -> number of raters (runs)
            that gave it. Every item must have the same number of raters.

    Returns:
        The kappa value.
    """
    n_items = len(table)
    raters = sum(table[0].values())
    labels = set().union(*table)
    p_j = {c: sum(t[c] for t in table) / (n_items * raters) for c in labels}
    p_i = [(sum(v * v for v in t.values()) - raters) / (raters * (raters - 1)) for t in table]
    p_bar = sum(p_i) / n_items
    p_e = sum(p * p for p in p_j.values())
    return (p_bar - p_e) / (1 - p_e)


def wilson(k, n, z=1.96):
    """Wilson score interval for k successes out of n."""
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def percentile_ci(values, level=0.95):
    """Percentile interval of a list of bootstrap replicates."""
    s = sorted(values)
    lo = s[int((1 - level) / 2 * len(s))]
    hi = s[min(len(s) - 1, int((1 + level) / 2 * len(s)))]
    return lo, hi


def weighted_acc(items, pred, strata, sizes):
    """Stratum-weighted accuracy: sum over strata of (N_h / N) * acc_h."""
    by_h = defaultdict(list)
    for n, gold_label in items:
        by_h[strata[n]].append(gold_label == pred[n])
    total = sum(sizes[h] for h in by_h)
    return sum(sizes[h] / total * (sum(v) / len(v)) for h, v in by_h.items())


def bootstrap(items, stat, b, rng, strata=None):
    """Bootstrap replicates of stat(items), optionally resampling within strata."""
    if strata is None:
        return [stat([rng.choice(items) for _ in items]) for _ in range(b)]
    groups = defaultdict(list)
    for it in items:
        groups[strata[it[0]]].append(it)
    reps = []
    for _ in range(b):
        sample = []
        for g in groups.values():
            sample.extend(rng.choice(g) for _ in g)
        reps.append(stat(sample))
    return reps


def fmt_ci(lo, hi):
    """Format an interval as [lo, hi] in percent."""
    return f"[{lo * 100:.0f}%, {hi * 100:.0f}%]"


def weighted_confusion(items, pred, strata, sizes):
    """Population-weighted confusion matrix from a stratified sample.

    Each sampled article stands for N_h / n_h articles of its stratum (inverse
    inclusion probability), so the weighted counts estimate the confusion matrix
    of the whole population, not of the oversampled sample.

    Args:
        items: List of (nummer, silver_label).
        pred: Mapping nummer -> predicted label.
        strata: Mapping nummer -> stratum.
        sizes: Mapping stratum -> population size N_h.

    Returns:
        Dict silver_label -> Counter(predicted_label -> weighted count).
    """
    n_h = Counter(strata[n] for n, _ in items)
    conf = defaultdict(Counter)
    for n, g in items:
        conf[g][pred.get(n)] += sizes[strata[n]] / n_h[strata[n]]
    return conf


def prf(conf):
    """Per-tag precision, recall and F1 from a (possibly weighted) confusion matrix.

    Returns:
        Dict tag -> (precision, recall, f1); a value is nan when undefined.
    """
    out = {}
    for t in TAGS:
        tp = conf[t][t]
        predicted = sum(conf[g][t] for g in conf)
        actual = sum(conf[t].values())
        p = tp / predicted if predicted else float("nan")
        r = tp / actual if actual else float("nan")
        f = 2 * p * r / (p + r) if p == p and r == r and p + r else float("nan")
        out[t] = (p, r, f)
    return out


def nan_ci(values):
    """Percentile interval ignoring undefined (nan) replicates."""
    vals = [v for v in values if v == v]
    return percentile_ci(vals) if vals else (float("nan"), float("nan"))


def main():
    parser = argparse.ArgumentParser(description="Silver-set quality and run stability")
    parser.add_argument("--v1", default="silver_deontic_v1.csv")
    parser.add_argument("--v2", default="silver_deontic_v2.csv")
    parser.add_argument("--key", default="silver_v2_strata.csv")
    parser.add_argument("--runs", nargs="+", help="prediction CSVs (default: runs/gpt4o_*.csv)")
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    run_paths = args.runs or sorted(glob.glob("runs/gpt4o_*.csv"))
    runs = {p.split("/")[-1].removesuffix(".csv"): {n: label(r) for n, r in read_csv(p).items()}
            for p in run_paths}
    v1 = {n: label(r) for n, r in read_csv(args.v1).items() if n not in FEWSHOT}
    v2_rows = read_csv(args.v2)
    v2 = {n: label(r) for n, r in v2_rows.items()}
    key = read_csv(args.key)
    strata = {n: key[n]["stratum"] for n in v2}
    sizes = {key[n]["stratum"]: int(key[n]["stratum_size"]) for n in v2}
    flagged = {n for n, r in v2_rows.items() if r["v0_fit"] == "no" or r["category"]}
    combined = {**v1, **v2}

    print(f"runs: {', '.join(runs)}")
    print(f"silver v1 held-out n={len(v1)}, silver v2 n={len(v2)} "
          f"({len(flagged)} flagged), combined n={len(combined)}")

    print("\nquality per run")
    print(f"  {'run':16}{'v1 held-out':>13}{'v2 raw':>9}{'v2 weighted':>13}{'combined':>11}{'kappa':>8}")
    acc_v1, acc_v2w, acc_comb, kap = [], [], [], []
    for name, pred in runs.items():
        k1 = sum(pred.get(n) == g for n, g in v1.items())
        k2 = sum(pred.get(n) == g for n, g in v2.items())
        w2 = weighted_acc(list(v2.items()), pred, strata, sizes)
        kc = sum(pred.get(n) == g for n, g in combined.items())
        kp = cohen_kappa(list(combined.values()), [pred.get(n) for n in combined])
        acc_v1.append(k1 / len(v1)); acc_v2w.append(w2); acc_comb.append(kc / len(combined)); kap.append(kp)
        print(f"  {name:16}{k1:>7}/{len(v1):<5}{k2:>5}/{len(v2):<3}{w2:>12.3f}{kc:>7}/{len(combined):<3}{kp:>8.3f}")
    mean_sd = lambda xs: f"{statistics.mean(xs):.3f} ± {statistics.stdev(xs):.3f}" if len(xs) > 1 else f"{xs[0]:.3f}"
    print(f"  mean ± sd across runs: v1 {mean_sd(acc_v1)}, v2 weighted {mean_sd(acc_v2w)}, "
          f"combined {mean_sd(acc_comb)}, kappa {mean_sd(kap)}")

    ref = list(runs)[-1]
    pred = runs[ref]
    print(f"\nintervals (95%, run {ref}, {args.bootstrap} bootstrap replicates)")
    comb_items = list(combined.items())
    k = sum(pred.get(n) == g for n, g in comb_items)
    lo, hi = wilson(k, len(comb_items))
    reps = bootstrap(comb_items, lambda s: sum(pred.get(n) == g for n, g in s) / len(s), args.bootstrap, rng)
    print(f"  combined accuracy {k}/{len(comb_items)} = {k / len(comb_items):.3f}: "
          f"Wilson {fmt_ci(lo, hi)}, bootstrap {fmt_ci(*percentile_ci(reps))}")
    v2_items = list(v2.items())
    reps = bootstrap(v2_items, lambda s: weighted_acc(s, pred, strata, sizes), args.bootstrap, rng, strata)
    print(f"  v2 stratum-weighted {weighted_acc(v2_items, pred, strata, sizes):.3f}: "
          f"stratified bootstrap {fmt_ci(*percentile_ci(reps))}")
    reps = bootstrap(comb_items, lambda s: cohen_kappa([g for _, g in s], [pred.get(n) for n, _ in s]),
                     args.bootstrap, rng)
    lo, hi = percentile_ci(reps)
    print(f"  combined kappa {cohen_kappa([g for _, g in comb_items], [pred.get(n) for n, _ in comb_items]):.3f}: "
          f"bootstrap [{lo:.2f}, {hi:.2f}]")

    print("\nclean vs flagged (silver v2, all runs pooled)")
    for name_set, members in (("clean", set(v2) - flagged), ("flagged", flagged)):
        hits = sum(runs[r].get(n) == v2[n] for r in runs for n in members)
        tot = len(members) * len(runs)
        print(f"  {name_set:8} {hits}/{tot} = {hits / tot:.3f}  (n={len(members)} articles x {len(runs)} runs)")

    print("\nper tag, combined set, all runs pooled, unweighted (rows = silver label)")
    conf = defaultdict(Counter)
    for r in runs.values():
        for n, g in combined.items():
            conf[g][r.get(n)] += 1
    cols = TAGS + ["other"]
    print(f"  {'':14}" + "".join(f"{c[:6]:>8}" for c in cols) + f"{'recall':>9}{'precision':>11}")
    for t in TAGS:
        row = [conf[t][c] for c in TAGS] + [sum(v for c, v in conf[t].items() if c not in TAGS)]
        recall = conf[t][t] / max(1, sum(conf[t].values()))
        predicted = sum(conf[g][t] for g in conf)
        precision = conf[t][t] / predicted if predicted else float("nan")
        print(f"  {t:14}" + "".join(f"{v:>8}" for v in row) + f"{recall:>9.2f}{precision:>11.2f}")

    print(f"\nprecision / recall / F1, population estimate from silver v2 (run {ref})")
    print("  each v2 article weighted by N_h / n_h of its stratum; 95% stratified bootstrap intervals")
    point = prf(weighted_confusion(v2_items, pred, strata, sizes))
    reps = bootstrap(v2_items, lambda smp: prf(weighted_confusion(smp, pred, strata, sizes)),
                     args.bootstrap, rng, strata)
    print(f"  {'tag':14}{'precision':>22}{'recall':>22}{'F1':>8}")
    for t in TAGS:
        pp, rr, ff = point[t]
        p_lo, p_hi = nan_ci([r[t][0] for r in reps])
        r_lo, r_hi = nan_ci([r[t][1] for r in reps])
        print(f"  {t:14}{pp:>8.2f} [{p_lo:.2f}, {p_hi:.2f}]{rr:>9.2f} [{r_lo:.2f}, {r_hi:.2f}]{ff:>8.2f}")
    macro = [statistics.mean(r[t][2] for t in TAGS if r[t][2] == r[t][2]) for r in reps]
    m_lo, m_hi = percentile_ci(macro)
    print(f"  macro F1 {statistics.mean(point[t][2] for t in TAGS):.2f} [{m_lo:.2f}, {m_hi:.2f}]")
    per_run = {name: prf(weighted_confusion(v2_items, r, strata, sizes)) for name, r in runs.items()}
    print("  F1 per run: " + "; ".join(
        f"{name} " + " ".join(f"{t[:4]}={per_run[name][t][2]:.2f}" for t in TAGS) for name in runs))

    print(f"\nstability across {len(runs)} runs")
    common = sorted(set.intersection(*(set(r) for r in runs.values())))
    table = [Counter(r[n] for r in runs.values()) for n in common]
    unstable = [n for n, t in zip(common, table) if len(t) > 1]
    print(f"  articles in every run: {len(common)}; identical label in all runs: "
          f"{len(common) - len(unstable)} ({(len(common) - len(unstable)) / len(common):.1%}); "
          f"unstable: {len(unstable)}")
    if len(runs) > 2:
        print(f"  Fleiss' kappa across runs: {fleiss_kappa(table):.3f}")
    names = list(runs)
    pair = [cohen_kappa([runs[a][n] for n in common], [runs[b][n] for n in common])
            for i, a in enumerate(names) for b in names[i + 1:]]
    print(f"  pairwise Cohen's kappa between runs: mean {statistics.mean(pair):.3f}, "
          f"min {min(pair):.3f}, max {max(pair):.3f}")
    flips = Counter(tuple(sorted(t)) for t in table if len(t) > 1)
    print("  most common flips: " + "; ".join(f"{' <-> '.join(k)} ({v})" for k, v in flips.most_common(5)))

    majority = {n: t.most_common(1)[0][0] for n, t in zip(common, table)}
    km = sum(majority.get(n) == g for n, g in combined.items())
    print(f"  majority vote over runs, combined set: {km}/{len(combined)} = {km / len(combined):.3f} "
          f"(single runs: {min(acc_comb):.3f} to {max(acc_comb):.3f})")
    unstable_set = set(unstable)
    for name_set, members in (("stable", set(combined) - unstable_set), ("unstable", set(combined) & unstable_set)):
        if members:
            hits = sum(majority[n] == combined[n] for n in members)
            print(f"  {name_set:8} articles in the silver sets: {hits}/{len(members)} correct by majority vote")


if __name__ == "__main__":
    main()
