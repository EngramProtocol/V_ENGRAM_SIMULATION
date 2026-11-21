"""Đợt 2 (ppna-r1-dot2): mô hình iterative, nhiều biến thể trên cùng một mạng đã dựng.

Mỗi lần chạy dựng mạng một lần (join trên k-bucket, rồi ingest) và chạy nhiều biến
thể truy vấn trên đúng mạng đó. Trước mỗi biến thể, trạng thái bộ sinh số ngẫu nhiên,
đồng hồ mô phỏng và thống kê lookup được đặt lại đúng như ngay sau khi dựng mạng, nên
mỗi biến thể cho kết quả trùng từng số với một lần chạy main_simulation.py riêng cùng
cấu hình (đã kiểm với các file của đợt kiểm 17/11, xem README_dot2.md).

Các bước ingest khác nhau (đặt record oracle, ingest chạy hết ngân sách, r = 2 và 3,
Bucket-LSH) đều bắt đầu từ cùng trạng thái ngay sau join, nên các ô so ghép cặp được.

Kế hoạch (--plan):
  sem    cấu hình chính và các biến thể chỉ đổi truy vấn: Bảng 7 (có R_max = 30), bốn
         control, margin ablation, (c = 9, T = 5), truy vấn oracle; --loss thêm mất peer
         (r = 1, mức lồng nhau, chạy sau cùng)
  dec    phân tách khoảng cách: đặt record oracle, ingest chạy hết ngân sách, bảng định
         tuyến đầy đủ; mỗi cách dựng chạy truy vấn Ripple Search và truy vấn oracle
  lsh    Bucket-LSH trên overlay: khoá là băm của b bit đầu, mỗi probe một lookup
  loss   r = 2 và 3, không mất peer và mất các mức ở --loss
  ws     weak scaling: K = --k và các K ở --extra-k trên cùng một mạng
  probe  đo thời gian và bộ nhớ: join, ingest --probe-docs object đầu, --nq query

Chạy từ gốc repo:
  python3 ppna_r1/dot2/iterative.py --plan sem --dataset code --seed 1 --loss 0.20,0.30 --out f.json
"""
import os
import sys

# ---- cấu hình chung của mô hình iterative (đặt TRƯỚC khi import src.*) ----
BASE_ENV = {
    "SKIP_PAYLOAD": "1", "ROUTING_TABLE": "kbucket", "BOOTSTRAP": "join", "K_BUCKET": "20",
    "PQ_VARIANT": "m512", "SHARED_ORIGIN": "1", "NORMALIZE_ROWS": "1", "DIAG_BUILD": "1",
    "OVERLAP_STATS": "0", "MEASURE_OVERLAP": "0", "STOP_RULE": "stable",
    "FRONTIER_SCOPE": "all", "R_MAX": "15", "PARALLEL_ADC": "1", "ROUTING_MODE": "auto",
    "NUM_TABLES": "5", "PROBE_ORDER": "margin", "PROJ_FAMILY": "achlioptas",
    "META_ANCHORS": "1", "PLACEMENT_MODE": "scan",
}
# Số bảng L: mặc định 5 (cấu hình chính); kế hoạch lt của đợt 4 dùng --num-tables 8. Phải đặt trước
# khi import src.*, vì src.routing đọc NUM_TABLES lúc import.
for _i, _arg in enumerate(sys.argv):
    if _arg == "--num-tables" and _i + 1 < len(sys.argv):
        BASE_ENV["NUM_TABLES"] = str(int(sys.argv[_i + 1]))
    elif _arg.startswith("--num-tables="):
        BASE_ENV["NUM_TABLES"] = str(int(_arg.split("=", 1)[1]))
for _k, _v in BASE_ENV.items():
    if os.environ.get(_k, _v) != _v:
        raise SystemExit(f"{_k}={os.environ[_k]} khác cấu hình của đợt 2 ({_v}); bỏ biến này đi")
    os.environ[_k] = _v
for _p in ("JOIN_", "INGEST_"):
    for _s in ("STOP_RULE", "FRONTIER_SCOPE", "R_MAX"):
        if os.environ.get(_p + _s) is not None:
            raise SystemExit(f"không đặt {_p + _s}: quy tắc từng pha do script này đặt")
if not os.path.isdir("src"):
    raise SystemExit("chạy từ gốc repo (cần thấy thư mục src/)")
sys.path.insert(0, os.getcwd())

import argparse          # noqa: E402
import collections       # noqa: E402
import copy              # noqa: E402
import json              # noqa: E402
import random            # noqa: E402
import resource          # noqa: E402
import time              # noqa: E402

import numpy as np       # noqa: E402
import simpy             # noqa: E402

import main_simulation as ms            # noqa: E402  (dùng lại cách tính các trường JSON)
import src.network as netmod            # noqa: E402
import src.routing as rt                # noqa: E402
from src.diag import build_diagnostics  # noqa: E402
from src.evaluation import compute_stage5_metrics  # noqa: E402
from src.network import (bootstrap_network, data_ingestion_process,  # noqa: E402
                         query_pipeline_process, refresh_buckets,
                         reset_global_metadata_dht)
from src.oracle import (XorIndex, build_full_tables, remove_dead,  # noqa: E402
                        restore_routing_state, save_routing_state)

DEFAULT_RULES = ("stable", "all", 15)
K_SIZE = 20            # như main_simulation.K_SIZE (không dùng với k-bucket)
TARGET_K = 10          # như main_simulation (--target-k 10)


def peak_rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def gini(x):
    x = np.sort(np.asarray(x, dtype=float))
    if x.sum() <= 0:
        return 0.0
    n = len(x)
    return float((2 * np.arange(1, n + 1) - n - 1) @ x / (n * x.sum()))


class Snapshot:
    """Trạng thái cần đặt lại trước mỗi bước: random, numpy, đồng hồ, thống kê lookup."""

    def __init__(self, env_now):
        self.now = env_now
        self.rs = random.getstate()
        self.nps = np.random.get_state()
        self.lookup = copy.deepcopy(rt.LOOKUP_STATS)

    def restore(self):
        random.setstate(self.rs)
        np.random.set_state(self.nps)
        rt.LOOKUP_STATS = copy.deepcopy(self.lookup)
        return simpy.Environment(initial_time=self.now)


def set_query_rules(rules):
    sr, fs, rmax = rules
    rt.PHASE_RULES[None] = (sr, fs, int(rmax))
    rt.STOP_RULE, rt.FRONTIER_SCOPE, rt.DEFAULT_R_MAX = sr, fs, int(rmax)
    netmod.DEFAULT_R_MAX = int(rmax)


class ProbeStats:
    """Thống kê mỗi lookup của truy vấn: trùng với K peer gần nhất thật, lookup trả ít
    hơn K peer, phân bố số vòng, thứ hạng XOR (thay cho MEASURE_OVERLAP)."""

    def __init__(self, index):
        self.ix = index
        self.n = 0
        self.ov = 0.0
        self.full = 0
        self.short = 0
        self.hops = collections.Counter()
        self.has_dup = len(np.unique(index.hi)) < len(index.hi)

    def __call__(self, p_key, nodes, hops, rpcs, k):
        self.n += 1
        self.hops[int(hops)] += 1
        kk = min(k, len(self.ix))
        if len(nodes) < kk:
            self.short += 1
        true = {nd.node_id for nd in self.ix.closest(p_key, kk)}
        inter = len({nd.node_id for nd in nodes} & true)
        self.ov += inter / max(k, 1)
        self.full += inter == kk
        if not nodes:
            return []
        if self.has_dup:
            return self.ix.ranks(p_key, nodes)
        d = self.ix._dist(p_key)
        dv = d[[self.ix.pos[nd.node_id] for nd in nodes]]
        return [int(x) for x in (d[None, :] < dv[:, None]).sum(axis=1)]

    def summary(self):
        if self.n == 0:          # chế độ không có lookup đo được (các control ngẫu nhiên)
            return {"probe_lookups": 0, "truek_overlap_mean": None, "truek_full_frac": None,
                    "short_lookups": None, "short_lookup_frac": None, "query_hops_hist": {}}
        n = self.n
        return {"probe_lookups": self.n, "truek_overlap_mean": self.ov / n,
                "truek_full_frac": self.full / n, "short_lookups": self.short,
                "short_lookup_frac": self.short / n,
                "query_hops_hist": {str(h): c for h, c in sorted(self.hops.items())}}


class Ctx:
    def __init__(self, a):
        self.a = a
        D = f"./data/{a.dataset}"
        self.E = np.load(f"{D}_corpus_embeddings.npy")
        self.Q = np.load(f"{D}_query_embeddings.npy")
        self.codes = np.load(f"{D}_pq_codes_{a.pq}.npy")
        self.codebook = np.load(f"{D}_pq_codebook_{a.pq}.npy")
        self.gt_path = f"{D}_ground_truth.json"
        with open(self.gt_path, encoding="utf-8") as fh:
            self.gt = json.load(fh)
        self.n_files = a.num_files or len(self.E)
        self.n_run = min(a.nq, len(self.gt))
        self.nodes = None
        self.by_id = None
        self.out = {"plan": a.plan, "dataset": a.dataset, "seed": a.seed, "nodes": a.nodes,
                    "pq": a.pq, "dim": int(self.E.shape[1]),
                    "num_files": self.n_files, "n_query": self.n_run,
                    "commit": os.environ.get("RUN_COMMIT", ""), "env": dict(BASE_ENV),
                    "stages": {}, "variants": {}, "timing": {}}
        self.t_start = time.time()

    def tick(self, label, t0):
        self.out["timing"][label] = round(time.time() - t0, 2)


# ------------------------------------------------------------------ dựng mạng
def join_stage(ctx):
    a = ctx.a
    random.seed(a.seed)
    np.random.seed(a.seed % (2 ** 32))
    # số chiều lấy từ embedding (jina 896); với 1024 chiều trùng lời gọi mặc định cũ
    rt.initialize_lsh_projections(a.seed, vector_dim=int(ctx.E.shape[1]))
    reset_global_metadata_dht()
    set_query_rules(DEFAULT_RULES)
    t0 = time.time()
    env = simpy.Environment()
    holder = {}

    def _p(env):
        holder["nodes"] = yield env.process(bootstrap_network(env, a.nodes, K_SIZE))

    env.process(_p(env))
    env.run()
    ctx.nodes = holder["nodes"]
    ctx.by_id = {n.node_id: n for n in ctx.nodes}
    rt._ALL_NODES = ctx.nodes
    ctx.tick("join", t0)
    if getattr(a, "join_refresh", 0):
        # đợt 3: join đầy đủ như Kademlia gốc (làm mới k-bucket sau join). Cùng bộ sinh
        # số với kế hoạch refresh, nên base ở đây trùng refresh1_base của kế hoạch đó.
        # Không đụng random của Python và đồng hồ mô phỏng.
        rng = np.random.RandomState((a.seed * 104729 + 7) % (2 ** 32))
        ctx.out["join_refresh"] = {}
        for rnd in range(1, a.join_refresh + 1):
            t1 = time.time()
            info = refresh_buckets(ctx.nodes, rng, int(os.environ["K_BUCKET"]))
            ctx.tick(f"join_refresh{rnd}", t1)
            ctx.out["join_refresh"][str(rnd)] = info
            print(f"[join + làm mới {rnd}] {info['lookups']} lookup, contact TB "
                  f"{info['contacts_mean']:.1f} (min {info['contacts_min']})", flush=True)
    ctx.s_join = Snapshot(env.now)
    ctx.rs_join = save_routing_state(ctx.nodes)
    return ctx.s_join


def ingest_stage(ctx, label, placement="lookup", ingest_rule=DEFAULT_RULES, r=1,
                 bucket=None, oracle=None, doc_ids=None):
    """Ingest bắt đầu từ trạng thái ngay sau join. Trả dict thông tin bước dựng."""
    for n in ctx.nodes:
        n.RAM_Index.clear()
        n.BUCKETS.clear()
    netmod.INGEST_LOG.clear()
    reset_global_metadata_dht()
    netmod.METADATA_ANCHORS = int(r)
    rt.PHASE_RULES["ingest"] = tuple(ingest_rule[:2]) + (int(ingest_rule[2]),)
    env = ctx.s_join.restore()
    t0 = time.time()
    n_files = ctx.n_files

    def _p(env):
        yield env.process(data_ingestion_process(
            env, ctx.nodes, n_files, 30, data_label=ctx.a.dataset.upper(),
            doc_ids=doc_ids, placement=placement, oracle=oracle, bucket=bucket,
            vectors=ctx.E, pq_codes=ctx.codes))

    env.process(_p(env))
    env.run()
    ctx.tick(f"ingest_{label}", t0)
    if placement == "bucket":
        meta = np.array([sum(len(v) for v in n.BUCKETS.values()) for n in ctx.nodes])
    else:
        meta = np.array([len(n.RAM_Index) for n in ctx.nodes])
    t1 = time.time()
    diag = build_diagnostics(ctx.nodes, netmod.INGEST_LOG, netmod.METADATA_ANCHORS)
    ctx.tick(f"diag_{label}", t1)
    info = {"placement": placement, "ingest_rule": "%s/%s/R%d" % tuple(rt.PHASE_RULES["ingest"]),
            "r": int(r), "metadata_gini": gini(meta), "metadata_total": int(meta.sum()),
            "metadata_max": int(meta.max()), "lookup_stats_build": rt.lookup_stats_summary(),
            **diag}
    if bucket is not None:
        info["bucket_b"] = int(bucket["b"])
    ctx.out["stages"][label] = info
    snap = Snapshot(env.now)
    return {"label": label, "snap": snap, "info": info, "meta_gini": gini(meta),
            "meta_total": int(meta.sum()), "diag": diag}


# ------------------------------------------------------------------ biến thể truy vấn
def run_variant(ctx, stage, name, K=20, T=8, c=16, mode="semantic", rules=DEFAULT_RULES,
                order="margin", matches=None, live=None, oracle=None, bucket=None,
                collect=False, extra=None):
    a = ctx.a
    set_query_rules(rules)
    rt.PROBE_ORDER = order
    netmod._PROBE_DIAG.clear()
    rt._OVERLAP_STATS.clear()
    env = stage["snap"].restore()
    index = oracle if oracle is not None else XorIndex(live if live is not None else ctx.nodes)
    hook = ProbeStats(index)
    res = {"test": [], "uniq": [], "stats": [], "contacted": [], "reach": []}
    t0 = time.time()

    def _loop(env):
        for qi, item in enumerate(ctx.gt[:ctx.n_run]):
            q_id = item["query_id"]
            qv = ctx.Q[q_id - 1]
            col = {} if collect else None
            match = matches[qi] if matches is not None else None
            retrieved, hops, n_uniq, st = yield env.process(query_pipeline_process(
                env, ctx.nodes, qv, ctx.codebook, target_k=TARGET_K, k_query=K,
                multi_probe=T, random_routing=False, verbose=False, probe_bits=c, mode=mode,
                match=match, live_nodes=live, oracle=index, bucket=bucket,
                probe_hook=hook, collect=col))
            res["uniq"].append(n_uniq)
            res["stats"].append(st)
            res["test"].append({"query_id": q_id, "retrieved": retrieved, "hops": hops})
            if collect:
                cset = col["contacted"]
                res["contacted"].append(len(cset))
                tags = set()
                for nid in cset:
                    tags.update(ctx.by_id[nid].RAM_Index.keys())
                res["reach"].append(len(tags))

    env.process(_loop(env))
    env.run()
    dt = time.time() - t0
    out = summarize(ctx, stage, name, res, env, K, T, c, mode, rules, order, live, hook)
    out["seconds"] = round(dt, 2)
    if extra:
        out.update(extra)
    ctx.out["variants"][name] = out
    set_query_rules(DEFAULT_RULES)
    rt.PROBE_ORDER = "margin"
    print(f"[biến thể] {name}: R@5 = {out['recall_at_5']:.2f}, peer = {out['mean_contacted']:.1f}, "
          f"RPC = {out['mean_rpcs']:.0f}, {dt:.0f} giây", flush=True)
    return res


def summarize(ctx, stage, name, res, env, K, T, c, mode, rules, order, live, hook):
    """Các trường giống hệt JSON của main_simulation.py, cộng các trường mới của đợt 2."""
    a = ctx.a
    all_stats, uniq_cands = res["stats"], res["uniq"]
    m = compute_stage5_metrics(env, ctx.nodes, res["test"], ground_truth_path=ctx.gt_path)
    pq = ms._probe_diag_summary()
    out = {"dataset": a.dataset, "seed": a.seed, "nodes": a.nodes,
           "r": netmod.METADATA_ANCHORS, "k_query": K, "multi_probe": T,
           "random_routing": False, "n_query": ctx.n_run,
           "parallel_adc": netmod.PARALLEL_ADC,
           **pq,
           "reachable_recall5": ms._compute_reachable(a.dataset),
           "stop_rule": rt.STOP_RULE, "frontier_scope": rt.FRONTIER_SCOPE,
           "overlap_mean": (float(np.mean(rt._OVERLAP_STATS)) if rt._OVERLAP_STATS else None),
           "placement_mode": netmod.PLACEMENT_MODE, "placement_k": netmod.PLACEMENT_K,
           "fetch_top": netmod.FETCH_TOP,
           "probe_depth_mean": float(np.mean([s.get("probe_depth_mean", 0) for s in all_stats])),
           "probe_depth_p95": float(np.mean([s.get("probe_depth_p95", 0) for s in all_stats])),
           "probe_depth_max": max([s.get("probe_depth_max", 0) for s in all_stats], default=0),
           "shards_found": int(sum(s.get("shards_found", 0) for s in all_stats)),
           "shard_misses": int(sum(s.get("shard_misses", 0) for s in all_stats)),
           "hit_at_5": m.get("hit_at_5") if m else None,
           "recall_at_5": m.get("recall_at_5") if m else None,
           "recall_at_10": m.get("recall_at_10") if m else None,
           "mrr": m.get("mrr_score") if m else None,
           "mean_rounds": float(np.mean([s["rounds"] for s in all_stats])),
           "mean_rpcs": float(np.mean([s["rpcs"] for s in all_stats])),
           "disc_rounds": float(np.mean([s.get("disc_rounds", 0) for s in all_stats])),
           "disc_rpcs": float(np.mean([s.get("disc_rpcs", 0) for s in all_stats])),
           "disc_bytes": float(np.mean([s.get("disc_bytes", 0) for s in all_stats])),
           "pay_rounds": float(np.mean([s.get("pay_rounds", 0) for s in all_stats])),
           "pay_rpcs": float(np.mean([s.get("pay_rpcs", 0) for s in all_stats])),
           "pay_bytes": float(np.mean([s.get("pay_bytes", 0) for s in all_stats])),
           "candidate_tags": float(np.mean([s.get("candidate_tags", 0) for s in all_stats])),
           "latency_p50": float(np.percentile([s.get("latency_ms", 0) for s in all_stats], 50)),
           "latency_p95": float(np.percentile([s.get("latency_ms", 0) for s in all_stats], 95)),
           "latency_p99": float(np.percentile([s.get("latency_ms", 0) for s in all_stats], 99)),
           "r_max": all_stats[0].get("r_max", 15) if all_stats else 15,
           "lookups_total": int(sum(s.get("lookups_total", 0) for s in all_stats)),
           "lookups_at_cap": int(sum(s.get("lookups_at_cap", 0) for s in all_stats)),
           "mean_contacted": float(np.mean([s["contacted_nodes"] for s in all_stats])),
           "mean_candidates": float(np.mean(uniq_cands)),
           "metadata_gini": stage["meta_gini"], "metadata_total": stage["meta_total"],
           "rules": rt.rules_summary(),
           "lookup_stats": rt.lookup_stats_summary(),
           **stage["diag"]}
    # ---- trường mới của đợt 2 ----
    out.update({
        "variant": name, "stage": stage["label"], "routing_mode": mode,
        "probe_bits": c, "probe_order": order,
        "query_rule": "%s/%s/R%d" % tuple(rules),
        "n_live": len(live) if live is not None else len(ctx.nodes),
        "pct_contacted": 100.0 * float(np.mean([s["contacted_nodes"] for s in all_stats])) /
                         (len(live) if live is not None else len(ctx.nodes)),
        "per_query_hits5": [len(set(int(t.split("_")[1]) for t in r["retrieved"][:5]) &
                                {g["index"] for g in ctx.gt[i]["top_5_results"]})
                            for i, r in enumerate(res["test"])],
        **hook.summary(),
    })
    if mode == "bucket_lsh":
        out["bucket_probes_found"] = int(sum(s.get("bucket_probes_found", 0) for s in all_stats))
    return out


# ------------------------------------------------------------------ kế hoạch
def plan_sem(ctx):
    a = ctx.a
    join_stage(ctx)
    st = ingest_stage(ctx, "main")
    ix_all = XorIndex(ctx.nodes)
    base = run_variant(ctx, st, "base", oracle=None, collect=True)
    # Bảng 7: chỉ đổi quy tắc dừng và R_max ở pha truy vấn (join, ingest giữ stable/all/R15)
    for sr, fs, rmax in (("stable", "topk", 15), ("exhaust", "topk", 15), ("exhaust", "all", 15),
                         ("exhaust", "topk", 30), ("exhaust", "all", 30)):
        run_variant(ctx, st, f"t7_{sr}-{fs}_R{rmax}", rules=(sr, fs, rmax))
    # bốn control, khớp ngân sách theo từng query của cấu hình chính
    run_variant(ctx, st, "ctl_random_unique", mode="random_unique",
                matches=[{"n_touch": n} for n in base["contacted"]])
    run_variant(ctx, st, "ctl_random_keys", mode="keyed_lookup")
    run_variant(ctx, st, "ctl_random_slots", mode="random_slots")
    run_variant(ctx, st, "ctl_random_equalcand", mode="random_equalcand",
                matches=[{"cand_budget": n} for n in base["reach"]])
    # margin ablation, cặp c, truy vấn oracle
    run_variant(ctx, st, "abl_random_order", order="random")
    run_variant(ctx, st, "c9_T5", T=5, c=9)
    run_variant(ctx, st, "q_oracle", mode="oracle", oracle=ix_all)
    ctx.out["base_per_query"] = {"contacted": base["contacted"], "reach": base["reach"]}
    if a.loss:
        loss_levels(ctx, st, "loss", a.loss)


def loss_levels(ctx, st, prefix, levels):
    """Mất peer tĩnh sau ingest, các mức lồng nhau (mức sau giữ mọi peer đã chết của
    mức trước). Peer chết chọn bằng bộ sinh số riêng nên không đổi dòng số chính."""
    a = ctx.a
    perm = random.Random(a.seed + 555).sample(range(len(ctx.nodes)), len(ctx.nodes))
    for f in sorted(levels):
        n_dead = int(round(len(ctx.nodes) * f))
        dead = {ctx.nodes[i] for i in perm[:n_dead]}
        live = remove_dead(ctx.nodes, dead)
        run_variant(ctx, st, f"{prefix}{f:.2f}", live=live,
                    extra={"loss": f, "n_dead": n_dead})


def plan_loss(ctx):
    a = ctx.a
    join_stage(ctx)
    for r in a.r_list:
        restore_routing_state(ctx.nodes, ctx.rs_join)
        st = ingest_stage(ctx, f"r{r}", r=r)
        run_variant(ctx, st, f"r{r}_loss0.00", extra={"loss": 0.0, "n_dead": 0})
        loss_levels(ctx, st, f"r{r}_loss", a.loss)
    restore_routing_state(ctx.nodes, ctx.rs_join)


def plan_dec(ctx):
    a = ctx.a
    join_stage(ctx)
    ix_all = XorIndex(ctx.nodes)
    # bảng join
    st = ingest_stage(ctx, "Po_Tj", placement="oracle", oracle=ix_all)
    run_variant(ctx, st, "Po_Tj_Qr")
    run_variant(ctx, st, "Po_Tj_Qo", mode="oracle", oracle=ix_all)
    st = ingest_stage(ctx, "Pfull_Tj", ingest_rule=("exhaust", "all", 15))
    run_variant(ctx, st, "Pfull_Tj_Qr")
    run_variant(ctx, st, "Pfull_Tj_Qo", mode="oracle", oracle=ix_all)
    # bảng đầy đủ (bộ sinh số riêng, không đổi dòng số chính)
    t0 = time.time()
    ft = build_full_tables(ctx.nodes, int(os.environ["K_BUCKET"]),
                           np.random.RandomState((a.seed * 7919 + 17) % (2 ** 32)))
    ctx.tick("full_tables", t0)
    ctx.out["full_tables"] = ft
    st = ingest_stage(ctx, "Pr_Tf")
    run_variant(ctx, st, "Pr_Tf_Qr")
    run_variant(ctx, st, "Pr_Tf_Qo", mode="oracle", oracle=ix_all)
    st = ingest_stage(ctx, "Po_Tf", placement="oracle", oracle=ix_all)
    run_variant(ctx, st, "Po_Tf_Qr")
    run_variant(ctx, st, "Po_Tf_Qo", mode="oracle", oracle=ix_all)
    restore_routing_state(ctx.nodes, ctx.rs_join)


def plan_lsh(ctx):
    a = ctx.a
    join_stage(ctx)
    bucket = {"b": int(a.lsh_b)}
    st = ingest_stage(ctx, f"bucket_b{a.lsh_b}", placement="bucket", bucket=bucket,
                      ingest_rule=a.ingest_rule)
    run_variant(ctx, st, f"bucket_b{a.lsh_b}_T{a.T}", T=a.T, mode="bucket_lsh", bucket=bucket,
                extra={"bucket_b": int(a.lsh_b)})


def plan_tk(ctx):
    """Đợt 3: các điểm T và K của Bảng 5 trên mô hình iterative, cùng một mạng.
    Biến thể base trùng từng số với base của nhóm sem ở đợt 2 (cùng seed)."""
    join_stage(ctx)
    st = ingest_stage(ctx, "main")
    run_variant(ctx, st, "base")
    for T in (1, 3, 5, 12):
        run_variant(ctx, st, f"T{T}_K20", T=T)
    for K in (10, 40, 80):
        run_variant(ctx, st, f"T8_K{K}", K=K)


def plan_wl(ctx):
    """Đợt 3: một điểm iterative cho mỗi workload của R1-4, kèm control random equal
    peers khớp số peer theo từng query."""
    join_stage(ctx)
    st = ingest_stage(ctx, "main")
    base = run_variant(ctx, st, "base", collect=True)
    run_variant(ctx, st, "ctl_random_unique", mode="random_unique",
                matches=[{"n_touch": n} for n in base["contacted"]])


def plan_refresh(ctx):
    """Đợt 3: join đầy đủ như Kademlia gốc, tức thêm vòng làm mới k-bucket sau join
    (refresh_buckets). Sau mỗi vòng: ingest lại từ đầu (cùng trạng thái số ngẫu nhiên
    như các kế hoạch khác) rồi chạy cấu hình chính, full round budget và truy vấn
    oracle. Vòng làm mới dùng bộ sinh số riêng nên ghép cặp được với nhóm sem."""
    a = ctx.a
    join_stage(ctx)
    rng = np.random.RandomState((a.seed * 104729 + 7) % (2 ** 32))
    ctx.out["refresh"] = {}
    for rnd in range(1, a.refresh_rounds + 1):
        rt.LOOKUP_STATS = {}
        t0 = time.time()
        info = refresh_buckets(ctx.nodes, rng, int(os.environ["K_BUCKET"]))
        ctx.tick(f"refresh{rnd}", t0)
        info["lookup_stats"] = rt.lookup_stats_summary()
        ctx.out["refresh"][str(rnd)] = info
        print(f"[làm mới {rnd}] {info['lookups']} lookup, contact TB {info['contacts_mean']:.1f} "
              f"(min {info['contacts_min']})", flush=True)
        st = ingest_stage(ctx, f"refresh{rnd}")
        run_variant(ctx, st, f"refresh{rnd}_base")
        run_variant(ctx, st, f"refresh{rnd}_t7_exhaust-all_R15", rules=("exhaust", "all", 15))
        run_variant(ctx, st, f"refresh{rnd}_q_oracle", mode="oracle", oracle=XorIndex(ctx.nodes))


def plan_ws(ctx):
    a = ctx.a
    join_stage(ctx)
    st = ingest_stage(ctx, "main")
    run_variant(ctx, st, f"K{a.k}", K=a.k)
    for k in a.extra_k:
        run_variant(ctx, st, f"K{k}", K=k)


def plan_probe(ctx):
    """Đo thời gian và bộ nhớ để ước lần chạy đầy đủ (smoke test ở 25.000, 50.000 peer)."""
    a = ctx.a
    join_stage(ctx)
    ctx.out["rss_after_join_mb"] = peak_rss_mb()
    n = min(a.probe_docs, ctx.n_files)
    st = ingest_stage(ctx, "probe", doc_ids=range(n))
    ctx.out["rss_after_ingest_mb"] = peak_rss_mb()
    run_variant(ctx, st, f"K{a.k}", K=a.k)
    t = ctx.out["timing"]
    q = ctx.out["variants"][f"K{a.k}"]["seconds"] / max(1, ctx.n_run)
    ctx.out["estimate_full"] = {
        "docs": len(ctx.E), "join_s": t["join"],
        "ingest_s": t["ingest_probe"] / max(1, n) * len(ctx.E),
        "query_s_per_variant_500q": q * 500,
        "note": "ước tuyến tính theo số object và số query"}


def plan_lt(ctx):
    """Đợt 4: L = 8 bảng trên mô hình iterative, cho mục chọn điểm vận hành (R2-2): T = 8, và T = 5
    (cùng 40 target với cấu hình chính), trên cùng một mạng. Chạy với --num-tables 8."""
    if int(os.environ["NUM_TABLES"]) != 8:
        raise SystemExit("kế hoạch lt cần --num-tables 8")
    join_stage(ctx)
    st = ingest_stage(ctx, "main")
    run_variant(ctx, st, "L8_T8")
    run_variant(ctx, st, "L8_T5", T=5)


PLANS = {"sem": plan_sem, "dec": plan_dec, "lsh": plan_lsh, "loss": plan_loss,
         "ws": plan_ws, "probe": plan_probe, "tk": plan_tk, "wl": plan_wl,
         "refresh": plan_refresh, "lt": plan_lt}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True, choices=list(PLANS))
    ap.add_argument("--dataset", default="code")
    ap.add_argument("--nodes", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=20235956)
    ap.add_argument("--nq", type=int, default=500)
    ap.add_argument("--num-files", type=int, default=None)
    ap.add_argument("--k", type=int, default=20, help="K của kế hoạch ws và probe")
    ap.add_argument("--extra-k", default="", help="K thêm cho kế hoạch ws, vd. 20")
    ap.add_argument("--T", type=int, default=8, help="T của Bucket-LSH")
    ap.add_argument("--lsh-b", type=int, default=None, help="độ rộng bucket b (kế hoạch lsh)")
    ap.add_argument("--loss", default="", help="mức mất peer, vd. 0.20,0.30")
    ap.add_argument("--r-list", default="2,3", help="r của kế hoạch loss")
    ap.add_argument("--probe-docs", type=int, default=2000)
    ap.add_argument("--pq", default="m512", help="biến thể PQ của dữ liệu (jina: m448)")
    ap.add_argument("--ingest-rule", default="stable,all,15",
                    help="quy tắc dừng của ingest cho kế hoạch lsh, vd. exhaust,all,15")
    ap.add_argument("--refresh-rounds", type=int, default=2, help="số vòng làm mới bucket")
    ap.add_argument("--join-refresh", type=int, default=0,
                    help="số vòng làm mới k-bucket ngay sau join, cho mọi kế hoạch (0 = join cũ)")
    ap.add_argument("--num-tables", type=int, default=5,
                    help="số bảng L (đọc trước khi import src.*; kế hoạch lt: 8)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    _ir = a.ingest_rule.split(",")
    if len(_ir) != 3 or _ir[0] not in ("stable", "exhaust") or _ir[1] not in ("all", "topk"):
        raise SystemExit("--ingest-rule phải có dạng stable|exhaust,all|topk,R_max")
    a.ingest_rule = (_ir[0], _ir[1], int(_ir[2]))
    a.loss = [float(x) for x in a.loss.split(",") if x.strip()]
    a.extra_k = [int(x) for x in a.extra_k.split(",") if x.strip()]
    a.r_list = [int(x) for x in a.r_list.split(",") if x.strip()]
    if a.plan == "lsh" and a.lsh_b is None:
        raise SystemExit("kế hoạch lsh cần --lsh-b")
    if a.plan == "refresh" and a.join_refresh:
        raise SystemExit("kế hoạch refresh tự làm mới bucket; không dùng thêm --join-refresh")
    ctx = Ctx(a)
    print(f"[*] mô hình iterative | kế hoạch {a.plan} | {a.dataset} | N = {a.nodes} | seed {a.seed} | "
          f"{ctx.n_files} object | {ctx.n_run} query | PQ {a.pq} | {ctx.E.shape[1]} chiều", flush=True)
    PLANS[a.plan](ctx)
    ctx.out["timing"]["total"] = round(time.time() - ctx.t_start, 2)
    ctx.out["peak_rss_mb"] = peak_rss_mb()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(ctx.out, fh, indent=1, default=float)
    os.replace(tmp, a.out)
    print(f"-> Lưu: {a.out} | {ctx.out['timing']['total']:.0f} giây | "
          f"RSS đỉnh {ctx.out['peak_rss_mb']:.0f} MB", flush=True)


if __name__ == "__main__":
    main()
