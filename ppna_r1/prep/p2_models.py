#!/usr/bin/env python3
"""Bước p2: embedding của model khác cho R1-4.

  e5   : intfloat/e5-large-v2 (1024 chiều) trên code và SciFact, tiền tố
         "query: " và "passage: " như Evo-Engram; PQ m = 512.
         Ra bộ dữ liệu code_e5, scifact_e5.
  jina : jinaai/jina-code-embeddings-0.5b (896 chiều) trên code, prompt
         nl2code_query và nl2code_document; PQ m = 448 để giữ hai chiều mỗi
         sub-vector như m = 512 ở 1024 chiều. Ra bộ dữ liệu code_jina.

Cả ba model cắt văn bản ở 512 token, như BGE của bản gốc. Corpus và 500 query
giữ nguyên văn bản của bộ BGE (data/{code,scifact}_corpus_texts.json và
query_text trong ground truth). Ground truth là top-10 chính xác trong không
gian của chính model đó.

Embedding corpus được lưu theo khối vào data/_prep_cache/, nên chạy lại sau
khi bị ngắt sẽ tiếp tục từ khối dở.
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (CACHE, DATA, SMOKE_DIR, angle_stats, die, encode_chunked,  # noqa: E402
                    exact_topk, lib_versions, load_json, log, make_gt, norm_stats,
                    save_dataset, torch_setup, train_pq, update_manifest, write_summary)

SPECS = {
    "e5": {"hf": "intfloat/e5-large-v2", "dim": 1024, "pq_m": 512, "bases": ["code", "scifact"],
           "q_prefix": "query: ", "d_prefix": "passage: ", "batch": 32, "max_len": 512},
    "jina": {"hf": "jinaai/jina-code-embeddings-0.5b", "dim": 896, "pq_m": 448, "bases": ["code"],
             "prompt_q": "nl2code_query", "prompt_d": "nl2code_document",
             "q_prefix": "Find the most relevant code snippet given the following query:\n",
             "d_prefix": "Candidate code snippet:\n", "batch": 16, "max_len": 512,
             "left_pad": True},
}


def make_encoders(spec, fake=False):
    """Trả về (enc_query, enc_doc, info). fake=True chỉ dùng để thử pipeline cục bộ."""
    if fake:
        d = spec["dim"]

        def _fake(texts, salt):
            out = np.empty((len(texts), d), dtype=np.float32)
            for i, t in enumerate(texts):
                r = np.random.default_rng(abs(hash((salt, t))) % (2 ** 32))
                v = r.standard_normal(d).astype(np.float32)
                out[i] = v / np.linalg.norm(v)
            return out
        return (lambda t: _fake(t, "q")), (lambda t: _fake(t, "d")), {"fake": True}

    torch, dev, nthreads = torch_setup()
    from sentence_transformers import SentenceTransformer
    kw = {"device": dev}
    if spec.get("left_pad"):
        kw["tokenizer_kwargs"] = {"padding_side": "left"}
    log(f"nạp {spec['hf']} trên {dev}, {nthreads} luồng")
    model = SentenceTransformer(spec["hf"], **kw)
    model.max_seq_length = spec["max_len"]
    prompts = dict(getattr(model, "prompts", {}) or {})
    use_prompts = spec.get("prompt_q") in prompts and spec.get("prompt_d") in prompts
    try:
        dim = int(model.get_sentence_embedding_dimension() or 0)
    except Exception:  # noqa: BLE001
        dim = 0
    info = {"device": dev, "threads": nthreads, "max_seq_length": model.max_seq_length,
            "dim": dim, "prompt_mode": "prompt_name" if use_prompts else "prefix"}
    if use_prompts:
        info["prompts"] = {k: prompts[k] for k in (spec["prompt_q"], spec["prompt_d"])}

    def _enc(texts, prompt_name, prefix):
        texts = list(texts)
        kwargs = dict(batch_size=spec["batch"], show_progress_bar=False,
                      convert_to_numpy=True, normalize_embeddings=True)
        if use_prompts and prompt_name:
            out = model.encode(texts, prompt_name=prompt_name, **kwargs)
        else:
            out = model.encode([prefix + t for t in texts], **kwargs)
        return np.ascontiguousarray(out, dtype=np.float32)

    enc_q = lambda t: _enc(t, spec.get("prompt_q"), spec["q_prefix"])  # noqa: E731
    enc_d = lambda t: _enc(t, spec.get("prompt_d"), spec["d_prefix"])  # noqa: E731
    return enc_q, enc_d, info


def top5_overlap(I_new, base):
    """Tỉ lệ láng giềng top-5 của model mới cũng nằm trong top-5 của BGE."""
    gt_bge = load_json(DATA / f"{base}_ground_truth.json")
    ov = []
    for i, g in enumerate(gt_bge):
        a = set(int(r["index"]) for r in g["top_5_results"])
        b = set(int(x) for x in I_new[i][:5])
        ov.append(len(a & b) / 5.0)
    return float(np.mean(ov))


def run_model(key, smoke=False, fake=False):
    spec = SPECS[key]
    enc_q, enc_d, info = make_encoders(spec, fake=fake)
    if not fake and info["dim"] and info["dim"] != spec["dim"]:
        die(f"{spec['hf']} trả {info['dim']} chiều, chờ {spec['dim']}")
    res = {"model": spec["hf"], "encoder": info, "datasets": {}}
    for base in spec["bases"]:
        name = f"{base}_{key}"
        texts = load_json(DATA / f"{base}_corpus_texts.json")
        gt0 = load_json(DATA / f"{base}_ground_truth.json")
        queries = [g["query_text"] for g in gt0]
        src = [int(g["source_corpus_index"]) for g in gt0] if "source_corpus_index" in gt0[0] else None
        if smoke:
            n_doc, n_q = 64, 16
            t0 = time.time()
            Ec = enc_d(texts[:n_doc])
            t_doc = (time.time() - t0) / n_doc
            Eq = enc_q(queries[:n_q])
            r = {"smoke": True, "corpus_shape": list(Ec.shape), "query_shape": list(Eq.shape),
                 "corpus_norm": norm_stats(Ec), "query_norm": norm_stats(Eq),
                 "seconds_per_doc": t_doc,
                 "eta_full_corpus_minutes": t_doc * len(texts) / 60}
            SMOKE_DIR.mkdir(parents=True, exist_ok=True)
            np.save(SMOKE_DIR / f"{name}_smoke_corpus.npy", Ec)
            log(f"[{name}] smoke: {Ec.shape}, {t_doc:.3f} giây/văn bản, "
                f"ước cả corpus {r['eta_full_corpus_minutes']:.0f} phút")
            res["datasets"][name] = r
            continue
        t0 = time.time()
        Ec = encode_chunked(enc_d, texts, CACHE / f"{name}_corpus", chunk=1000, label=name)
        t_corpus = time.time() - t0
        Eq = enc_q(queries)
        if Ec.shape != (len(texts), spec["dim"]) or Eq.shape != (len(queries), spec["dim"]):
            die(f"[{name}] kích thước sai: corpus {Ec.shape}, query {Eq.shape}")
        D, I = exact_topk(Eq, Ec)
        gt = make_gt(queries, texts, D, I, source_idx=src)
        cb, codes, mse, t_pq = train_pq(Ec, spec["pq_m"])
        save_dataset(name, Ec, Eq, texts, gt, [(spec["pq_m"], cb, codes)])
        ang = angle_stats(Eq, Ec, I)
        r = {"corpus_shape": list(Ec.shape), "query_shape": list(Eq.shape),
             "corpus_norm": norm_stats(Ec), "query_norm": norm_stats(Eq),
             "angles": ang, "top5_overlap_with_bge": top5_overlap(I, base),
             "pq_m": spec["pq_m"], "pq_mse": mse, "pq_seconds": t_pq,
             "corpus_seconds": t_corpus}
        if src is not None:
            r["source_in_gt10"] = float(np.mean([g["source_in_gt10"] for g in gt]))
        res["datasets"][name] = r
        update_manifest({"name": name, "corpus": len(texts), "queries": len(queries),
                         "angle_mean": ang["angle_mean"], "dim": spec["dim"],
                         "model": spec["hf"], "pq_variant": f"m{spec['pq_m']}"})
        log(f"[{name}] xong: góc {ang['angle_mean']:.1f}°, trùng top-5 với BGE "
            f"{100 * r['top5_overlap_with_bge']:.1f}%, PQ MSE {mse:.4f}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=sorted(SPECS) + ["all"], default="all")
    ap.add_argument("--smoke", action="store_true",
                    help="nhúng 64 văn bản và 16 query để kiểm model và ước thời gian")
    ap.add_argument("--fake-encoder", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    keys = sorted(SPECS) if args.model == "all" else [args.model]
    for key in keys:
        t0 = time.time()
        res = run_model(key, smoke=args.smoke, fake=args.fake_encoder)
        res["versions"] = lib_versions()
        res["seconds"] = time.time() - t0
        write_summary(f"p2_{key}{'_smoke' if args.smoke else ''}", res)
    log("p2 xong")


if __name__ == "__main__":
    main()
