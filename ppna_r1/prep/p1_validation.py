#!/usr/bin/env python3
"""Bước p1: tập query validation cho CodeSearchNet và SciFact (R1-5).

Dùng để chọn độ rộng Bucket-LSH trên một tập query tách khỏi tập đánh giá.

Code: dựng lại đúng corpus 20.000 hàm của prepare/01_build_corpora.ipynb từ
parquet CodeSearchNet trên Hugging Face, kiểm từng văn bản khớp
data/code_corpus_texts.json, và kiểm câu đầu docstring của hàm nguồn khớp từng
query đánh giá. Query validation là câu đầu docstring của 500 hàm khác trong
corpus, chọn bằng seed riêng, không trùng nguyên văn với query đánh giá nào.

SciFact: kiểm 500 claim đánh giá đều có trong bộ claim tải về, rồi lấy 500
claim chưa dùng, xáo bằng seed riêng, làm validation.

Embedding bằng BAAI/bge-large-en-v1.5 như bản gốc (chuẩn hoá, không instruction).
Trước khi nhúng, nhúng lại các query đánh giá và so với file đã có, để chắc
embedding trên server cùng không gian với embedding gốc.

Ra: data/{code,scifact}_val_query_embeddings.npy và _val_ground_truth.json.
"""
import argparse
import random
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DATA, N_VAL, SEED, SMOKE_DIR, VAL_SEED, angle_stats, die,  # noqa: E402
                    exact_topk, lib_versions, load_json, log, make_gt, save_json,
                    save_npy, torch_setup, write_summary)

CSN_REPO = "code-search-net/code_search_net"
SCIFACT_REPO = "BeIR/scifact"
N_CORPUS_CODE, N_QUERY = 20000, 500


# ---- chép nguyên văn từ prepare/01_build_corpora.ipynb, CELL 2 ----
def strip_docstring(code_str, doc_str):
    if doc_str and doc_str.strip() and doc_str.strip() in code_str:
        return code_str.replace(doc_str.strip(), ' ', 1), True
    stripped = re.sub(r'("""|\'\'\')(.*?)(\1)', ' ', code_str, count=1, flags=re.DOTALL)
    return stripped, (stripped != code_str)


def first_sentence(doc):
    doc = re.sub(r'\s+', ' ', str(doc)).strip()
    m = re.split(r'(?<=[.!?])\s', doc)
    return (m[0] if m else doc)[:200]
# ---- hết phần chép ----


def rebuild_code_corpus(stored_texts):
    from huggingface_hub import hf_hub_download, list_repo_files
    import pandas as pd

    files = list_repo_files(CSN_REPO, repo_type="dataset")
    train_files = [f for f in files
                   if f.endswith(".parquet") and "train" in f.lower() and "python" in f.lower()]
    log(f"[code] parquet train python: {train_files}")
    if not train_files:
        die("không thấy parquet train python trong " + CSN_REPO)
    tried = []
    for fname in train_files:
        fp = hf_hub_download(repo_id=CSN_REPO, filename=fname, repo_type="dataset")
        ds = pd.read_parquet(fp).to_dict("records")
        log(f"[code] {fname}: {len(ds):,} hàm")
        corpus_texts, corpus_docs, seen = [], [], set()
        for row in ds:
            code = row.get('func_code_string') or ''
            doc = row.get('func_documentation_string') or ''
            if len(doc.split()) < 5:
                continue
            code_wo, ok = strip_docstring(code, doc)
            code_wo = re.sub(r'\s+', ' ', code_wo).strip()
            if len(code_wo) < 40 or code_wo in seen:
                continue
            seen.add(code_wo)
            corpus_texts.append(code_wo)
            corpus_docs.append(doc)
            if len(corpus_texts) >= N_CORPUS_CODE:
                break
        n_same = sum(1 for a, b in zip(corpus_texts, stored_texts) if a == b)
        tried.append({"file": fname, "n_rows": len(ds), "n_built": len(corpus_texts),
                      "n_match": n_same})
        log(f"[code] khớp {n_same:,}/{len(stored_texts):,} văn bản với data/code_corpus_texts.json")
        if corpus_texts == stored_texts:
            return corpus_texts, corpus_docs, fname, tried
    die("không dựng lại được corpus code khớp từng văn bản; xem các dòng 'khớp' ở trên")


def code_validation(n_val):
    stored_texts = load_json(DATA / "code_corpus_texts.json")
    gt = load_json(DATA / "code_ground_truth.json")
    corpus_texts, corpus_docs, fname, tried = rebuild_code_corpus(stored_texts)

    cand = [i for i in range(len(corpus_texts))
            if len(first_sentence(corpus_docs[i]).split()) >= 4]
    stored_q = [g["query_text"] for g in gt]
    stored_src = [int(g["source_corpus_index"]) for g in gt]
    # Hàm nguồn của 500 query đánh giá lấy thẳng từ ground truth đã có; kiểm
    # docstring dựng lại cho đúng từng câu query.
    n_text = sum(1 for i, q in zip(stored_src, stored_q) if first_sentence(corpus_docs[i]) == q)
    log(f"[code] câu đầu docstring của hàm nguồn khớp query đánh giá: {n_text}/{N_QUERY}")
    if n_text != N_QUERY:
        die("docstring dựng lại không khớp query đánh giá; dừng để tập validation chắc chắn tách rời")
    # Chỉ để đối chiếu: phép chọn ngẫu nhiên của notebook có tái lập được không.
    random.seed(SEED)
    rng_ok = random.sample(cand, N_QUERY) == stored_src
    log(f"[code] tái lập phép chọn query của notebook bằng seed: {'có' if rng_ok else 'không'}")
    n_src = N_QUERY

    test_set, src_set = set(stored_q), set(stored_src)
    pool = [i for i in cand if i not in src_set and first_sentence(corpus_docs[i]) not in test_set]
    rng = random.Random(VAL_SEED)
    rng.shuffle(pool)
    v_idx, v_texts, seen = [], [], set()
    for i in pool:
        t = first_sentence(corpus_docs[i])
        if t in seen:
            continue
        seen.add(t)
        v_idx.append(i)
        v_texts.append(t)
        if len(v_idx) >= n_val:
            break
    info = {"parquet_file": fname, "tried": tried, "n_candidates": len(cand),
            "n_pool": len(pool), "test_text_match": n_text, "test_source_match": n_src,
            "notebook_rng_reproduced": rng_ok,
            "n_val": len(v_idx), "overlap_with_test_text": len(set(v_texts) & test_set),
            "overlap_with_test_source": len(set(v_idx) & src_set)}
    return stored_texts, v_texts, v_idx, stored_q, info


def scifact_claim_sources():
    """Thử lần lượt các cách đọc claim của BeIR/scifact, giữ đúng thứ tự gốc."""
    try:
        from datasets import load_dataset
        ds = load_dataset(SCIFACT_REPO, "queries", split="queries")
        yield "datasets.load_dataset", [str(r.get("text") or "").strip() for r in ds]
    except Exception as e:  # noqa: BLE001
        log(f"[scifact] load_dataset không dùng được: {str(e)[:160]}")
    try:
        import gzip
        import json
        from huggingface_hub import hf_hub_download
        fp = hf_hub_download(SCIFACT_REPO, "queries.jsonl.gz", repo_type="dataset")
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        yield "queries.jsonl.gz", [str(r.get("text") or "").strip() for r in rows]
    except Exception as e:  # noqa: BLE001
        log(f"[scifact] queries.jsonl.gz không dùng được: {str(e)[:160]}")
    try:
        import pandas as pd
        from huggingface_hub import hf_hub_download, list_repo_files
        files = [f for f in list_repo_files(SCIFACT_REPO, repo_type="dataset")
                 if "quer" in f.lower() and f.endswith(".parquet")]
        frames = [pd.read_parquet(hf_hub_download(SCIFACT_REPO, f, repo_type="dataset"))
                  for f in sorted(files)]
        if frames:
            df = pd.concat(frames, ignore_index=True)
            yield "parquet " + ",".join(sorted(files)), [str(x or "").strip() for x in df["text"]]
    except Exception as e:  # noqa: BLE001
        log(f"[scifact] parquet không dùng được: {str(e)[:160]}")


def scifact_validation(n_val):
    gt = load_json(DATA / "scifact_ground_truth.json")
    stored_q = [g["query_text"] for g in gt]
    tried = []
    test_set = set(stored_q)
    for method, raw in scifact_claim_sources():
        claims = [c for c in raw if len(c.split()) >= 3]
        n_found = len(test_set & set(claims))
        shuffled = list(claims)
        random.seed(SEED)
        random.shuffle(shuffled)
        rng_ok = shuffled[:N_QUERY] == stored_q
        tried.append({"method": method, "n_raw": len(raw), "n_claims": len(claims),
                      "test_found": n_found, "notebook_rng_reproduced": rng_ok})
        log(f"[scifact] {method}: {len(claims)} claim, chứa {n_found}/{len(test_set)} claim đánh giá "
            f"khác nhau; tái lập phép xáo của notebook: {'có' if rng_ok else 'không'}")
        if n_found == len(test_set):
            # Claim chưa dùng, theo thứ tự gốc, xáo bằng seed riêng.
            unused, seen = [], set()
            for c in claims:
                if c in test_set or c in seen:
                    continue
                seen.add(c)
                unused.append(c)
            random.Random(VAL_SEED).shuffle(unused)
            v_texts = unused[:n_val]
            if len(v_texts) < n_val:
                log(f"[scifact] CẢNH BÁO: chỉ còn {len(v_texts)} claim chưa dùng")
            info = {"method": method, "tried": tried, "n_claims": len(claims),
                    "test_text_match": n_found, "test_unique": len(test_set),
                    "notebook_rng_reproduced": rng_ok,
                    "n_unused": len(unused), "n_val": len(v_texts),
                    "overlap_with_test_text": len(set(v_texts) & test_set)}
            return load_json(DATA / "scifact_corpus_texts.json"), v_texts, stored_q, info
    die("không tìm thấy đủ 500 claim đánh giá của SciFact trong dữ liệu tải về")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true",
                    help="chạy đủ phần tải và kiểm, nhưng chỉ nhúng 20 query; ghi ra data/_prep_smoke/")
    args = ap.parse_args()
    t_all = time.time()
    n_val = 20 if args.smoke else N_VAL
    target = SMOKE_DIR if args.smoke else DATA

    log("[code] dựng lại corpus CodeSearchNet ...")
    code_corpus, code_v, code_vidx, code_test_q, code_info = code_validation(n_val)
    log("[scifact] đọc claim BeIR/scifact ...")
    sci_corpus, sci_v, sci_test_q, sci_info = scifact_validation(n_val)

    torch, dev, nthreads = torch_setup()
    from sentence_transformers import SentenceTransformer
    log(f"nạp BAAI/bge-large-en-v1.5 trên {dev}, {nthreads} luồng")
    model = SentenceTransformer("BAAI/bge-large-en-v1.5", device=dev)

    def enc(texts):
        return np.ascontiguousarray(model.encode(
            list(texts), batch_size=64, show_progress_bar=False, convert_to_numpy=True,
            normalize_embeddings=True), dtype=np.float32)

    out = {"smoke": args.smoke, "versions": lib_versions(), "device": dev,
           "max_seq_length": int(getattr(model, "max_seq_length", 0) or 0),
           "code": code_info, "scifact": sci_info}

    for name, test_q, v_texts, v_idx, corpus in (
            ("code", code_test_q, code_v, code_vidx, code_corpus),
            ("scifact", sci_test_q, sci_v, None, sci_corpus)):
        # 1) kiểm embedding trên server khớp embedding gốc
        n_chk = 20 if args.smoke else len(test_q)
        Eq_old = np.load(DATA / f"{name}_query_embeddings.npy")[:n_chk]
        t0 = time.time()
        Eq_new = enc(test_q[:n_chk])
        cos = (Eq_new * Eq_old).sum(axis=1)
        out[name]["bge_recheck"] = {"n": n_chk, "cos_min": float(cos.min()),
                                    "cos_mean": float(cos.mean()),
                                    "max_abs_diff": float(np.abs(Eq_new - Eq_old).max()),
                                    "seconds": time.time() - t0}
        log(f"[{name}] nhúng lại {n_chk} query đánh giá: cos nhỏ nhất {cos.min():.6f}, "
            f"trung bình {cos.mean():.6f}")
        # 2) nhúng query validation, ground truth trên corpus đã có
        Ev = enc(v_texts)
        E = np.load(DATA / f"{name}_corpus_embeddings.npy")
        D, I = exact_topk(Ev, E)
        gt = make_gt(v_texts, corpus, D, I, source_idx=v_idx)
        save_npy(Ev, Path(target) / f"{name}_val_query_embeddings.npy")
        save_json(gt, Path(target) / f"{name}_val_ground_truth.json", indent=2)
        st = angle_stats(Ev, E, I)
        out[name]["val_angles"] = st
        if v_idx is not None:
            out[name]["val_source_in_gt10"] = float(np.mean([g["source_in_gt10"] for g in gt]))
        log(f"[{name}] {len(v_texts)} query validation, góc tới GT5 trung bình {st['angle_mean']:.1f}°")

    out["seconds"] = time.time() - t_all
    write_summary("p1_validation_smoke" if args.smoke else "p1_validation", out)
    log("p1 xong")


if __name__ == "__main__":
    main()
