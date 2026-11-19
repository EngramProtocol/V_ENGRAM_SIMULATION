#!/usr/bin/env python3
"""Bước p3: corpus trung gian cho weak scaling (R1-3).

Weak scaling giữ tỉ lệ 2 văn bản mỗi peer: code (20k văn bản, 10k peer),
code50k (25k peer), code100k (50k peer). Bước này thêm code30k, code40k và
code70k cho 15k, 20k và 35k peer.

Như prepare/02_extend_weakscaling.ipynb, corpus cỡ S là S dòng đầu của
code100k, query là 500 query của bộ code, ground truth tính lại trên corpus cỡ
S, PQ m = 512 huấn luyện riêng cho từng cỡ.

Trước khi dựng, bước này dựng lại code50k bằng đúng quy trình và so với
code50k đã có (ground truth và sai số PQ), để kiểm quy trình mới cho kết quả
như notebook.
"""
import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DATA, angle_stats, die, exact_topk, lib_versions, load_json, log,  # noqa: E402
                    make_gt, pq_mse, save_dataset, train_pq, update_manifest, write_summary)

SCALES = [(30000, "code30k"), (40000, "code40k"), (70000, "code70k")]
if os.environ.get("P3_SCALES"):          # chỉ dùng khi thử trên dữ liệu giả
    SCALES = [(int(a), b) for a, b in (x.split(":") for x in os.environ["P3_SCALES"].split(","))]


def need(path):
    if not Path(path).exists():
        die(f"thiếu {path}; bộ code50k và code100k phải có sẵn trong data/ trên server")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="chỉ kiểm file và các phép so khớp, không dựng")
    args = ap.parse_args()
    t_all = time.time()

    E100 = np.load(need(DATA / "code100k_corpus_embeddings.npy"), mmap_mode="r")
    Eq100 = np.load(need(DATA / "code100k_query_embeddings.npy"))
    E50 = np.load(need(DATA / "code50k_corpus_embeddings.npy"), mmap_mode="r")
    gt50 = load_json(need(DATA / "code50k_ground_truth.json"))
    E20 = np.load(DATA / "code_corpus_embeddings.npy", mmap_mode="r")
    Eq20 = np.load(DATA / "code_query_embeddings.npy")
    gt_code = load_json(DATA / "code_ground_truth.json")
    tpath = DATA / "code100k_corpus_texts.json"
    texts100 = load_json(tpath) if tpath.exists() else None

    checks = {
        "code100k_shape": list(E100.shape),
        "prefix20k_equal": bool(np.array_equal(E100[:len(E20)], E20)),
        "prefix50k_equal": bool(np.array_equal(E100[:len(E50)], E50)),
        "queries_equal_code": bool(np.array_equal(Eq100, Eq20)),
        "queries_max_abs_diff": float(np.abs(Eq100 - Eq20).max()),
        "texts100_present": texts100 is not None,
    }
    log(f"kiểm tiền tố: 20k {checks['prefix20k_equal']}, 50k {checks['prefix50k_equal']}, "
        f"query trùng bộ code {checks['queries_equal_code']}")
    if not (checks["prefix20k_equal"] and checks["prefix50k_equal"]):
        die("code100k không chứa code và code50k làm tiền tố; quy trình dựng corpus trung gian không áp dụng được")
    query_texts = [g["query_text"] for g in gt_code]
    src = [int(g["source_corpus_index"]) for g in gt_code]

    out = {"smoke": args.smoke, "versions": lib_versions(), "checks": checks, "scales": {}}
    if args.smoke:
        out["seconds"] = time.time() - t_all
        write_summary("p3_scales_smoke", out)
        return

    # Dựng lại code50k bằng quy trình mới và so với bản của notebook
    E50c = np.ascontiguousarray(E50, dtype=np.float32)
    D, I = exact_topk(Eq100, E50c)
    old_I = np.array([[int(r["index"]) for r in g["top_10_results"]] for g in gt50])
    same_list = float(np.mean([np.array_equal(I[i], old_I[i]) for i in range(len(I))]))
    same_set = float(np.mean([set(I[i]) == set(old_I[i]) for i in range(len(I))]))
    cb_old = np.load(DATA / "code50k_pq_codebook_m512.npy")
    codes_old = np.load(DATA / "code50k_pq_codes_m512.npy")
    mse_old = pq_mse(E50c, cb_old, codes_old)
    _, _, mse_new, _ = train_pq(E50c, 512)
    out["rebuild_code50k"] = {"gt_top10_identical_order": same_list,
                              "gt_top10_identical_set": same_set,
                              "pq_mse_notebook": mse_old, "pq_mse_rebuilt": mse_new}
    log(f"dựng lại code50k: top-10 trùng thứ tự {100 * same_list:.1f}%, trùng tập {100 * same_set:.1f}%; "
        f"PQ MSE notebook {mse_old:.5f}, dựng lại {mse_new:.5f}")
    del E50c

    for S, name in SCALES:
        t0 = time.time()
        E = np.ascontiguousarray(E100[:S], dtype=np.float32)
        D, I = exact_topk(Eq100, E)
        texts = texts100[:S] if texts100 is not None else None
        gt = make_gt(query_texts, texts, D, I, source_idx=src)
        cb, codes, mse, t_pq = train_pq(E, 512)
        save_dataset(name, E, Eq100, texts, gt, [(512, cb, codes)])
        ang = angle_stats(Eq100, E, I)
        out["scales"][name] = {"corpus": S, "peers_at_2_docs_per_peer": S // 2,
                               "angles": ang, "pq_mse": mse,
                               "source_in_gt10": float(np.mean([g["source_in_gt10"] for g in gt])),
                               "seconds": time.time() - t0}
        update_manifest({"name": name, "corpus": S, "queries": len(query_texts),
                         "angle_mean": ang["angle_mean"], "dim": int(E.shape[1]),
                         "model": "BAAI/bge-large-en-v1.5", "pq_variant": "m512"})
        log(f"[{name}] xong: góc {ang['angle_mean']:.1f}°, PQ MSE {mse:.5f}")
        del E

    out["seconds"] = time.time() - t_all
    write_summary("p3_scales", out)
    log("p3 xong")


if __name__ == "__main__":
    main()
