"""Hàm dùng chung cho các bước chuẩn bị dữ liệu của đợt 1 (chạy trên server).

Thay cho các notebook Colab: mọi bước đều chạy được trên CPU. Quy ước giữ đúng
như prepare/README.md: embedding chuẩn hoá L2 lúc encode, ground truth là top-10
chính xác theo tích vô hướng, PQ bằng faiss.ProductQuantizer 8 bit.
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
# Hai biến môi trường dưới đây chỉ dùng khi thử script trên dữ liệu giả;
# chạy thật trên server thì để trống.
DATA = Path(os.environ.get("VENGRAM_DATA_DIR", REPO / "data"))
OUT = Path(os.environ.get("PREP_OUT_DIR", REPO / "ppna_r1" / "prep_out"))
CACHE = DATA / "_prep_cache"
SMOKE_DIR = DATA / "_prep_smoke"

SEED = 20235956          # seed của bản gốc (prepare/README.md)
VAL_SEED = SEED + 1      # seed riêng cho tập query validation
GT_TOPK = 10
N_VAL = 500


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def die(msg):
    log("LỖI: " + msg)
    sys.exit(1)


def save_json(obj, path, indent=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)


def save_npy(arr, path):
    """Ghi qua file tạm rồi đổi tên, để lần chạy bị ngắt không để lại file dở."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp.npy")
    np.save(tmp, arr)
    os.replace(tmp, path)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def summary_path(step):
    OUT.mkdir(parents=True, exist_ok=True)
    return OUT / f"{step}.json"


def write_summary(step, obj):
    obj = dict(obj)
    obj["step"] = step
    obj["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path = summary_path(step)
    save_json(obj, path, indent=2)
    try:
        shown = path.relative_to(REPO)
    except ValueError:
        shown = path
    log(f"đã ghi {shown}")


# ---------------------------------------------------------------- ground truth
def exact_topk(Eq, E, k=GT_TOPK, chunk=64):
    """Top-k chính xác theo tích vô hướng, giống faiss.IndexFlatIP.

    Trả về (D, I) sắp giảm dần theo độ tương đồng; hoà thì chỉ số nhỏ trước.
    Chia theo khối query để bộ nhớ không phụ thuộc kích thước corpus.
    """
    Eq = np.ascontiguousarray(Eq, dtype=np.float32)
    E = np.ascontiguousarray(E, dtype=np.float32)
    nq = len(Eq)
    D = np.empty((nq, k), dtype=np.float32)
    I = np.empty((nq, k), dtype=np.int64)
    for s in range(0, nq, chunk):
        S = Eq[s:s + chunk] @ E.T
        part = np.argpartition(-S, k - 1, axis=1)[:, :k]
        for r in range(S.shape[0]):
            cand = part[r]
            sims = S[r, cand]
            order = np.lexsort((cand, -sims))
            I[s + r] = cand[order]
            D[s + r] = sims[order]
    return D, I


def make_gt(query_texts, corpus_texts, D, I, source_idx=None):
    """Cùng định dạng với build_and_save() trong prepare/01_build_corpora.ipynb."""
    gt = []
    k = I.shape[1]
    for i, q in enumerate(query_texts):
        results = []
        for r in range(k):
            idx = int(I[i][r])
            snippet = ""
            if corpus_texts is not None:
                snippet = str(corpus_texts[idx]).replace("\n", " ")[:80]
            results.append({"rank": r + 1, "index": idx,
                            "cosine_similarity": float(D[i][r]),
                            "code_snippet": snippet})
        item = {"query_id": i + 1, "query_text": str(q),
                "top_5_results": results[:5], "top_10_results": results,
                "margin_top1_top10": float(D[i][0] - D[i][-1])}
        if source_idx is not None:
            src = int(source_idx[i])
            item["source_corpus_index"] = src
            item["source_in_gt10"] = bool(src in set(int(x) for x in I[i]))
        gt.append(item)
    return gt


def angle_stats(Eq, E, I, top=5):
    angs = []
    for i in range(len(Eq)):
        cos = E[I[i][:top]] @ Eq[i]
        angs.extend(np.degrees(np.arccos(np.clip(cos, -1, 1))))
    angs = np.array(angs)
    return {"angle_mean": float(angs.mean()),
            "angle_median": float(np.median(angs)),
            "angle_p90": float(np.percentile(angs, 90))}


def norm_stats(X):
    n = np.linalg.norm(X, axis=1)
    return {"norm_mean": float(n.mean()), "norm_min": float(n.min()),
            "norm_max": float(n.max())}


# ---------------------------------------------------------------------- PQ
def train_pq(E, m, nbits=8, seed=1234):
    """faiss.ProductQuantizer như các notebook gốc. seed 1234 là mặc định của faiss."""
    try:
        import faiss
    except ImportError:
        die("thiếu faiss; cài trong venv_prep: pip install faiss-cpu")
    E = np.ascontiguousarray(E, dtype=np.float32)
    d = E.shape[1]
    if d % m:
        die(f"số chiều {d} không chia hết cho m={m}")
    if hasattr(faiss, "omp_set_num_threads"):
        faiss.omp_set_num_threads(int(os.environ.get("PREP_THREADS", os.cpu_count() or 1)))
    pq = faiss.ProductQuantizer(d, m, nbits)
    if hasattr(pq, "cp") and hasattr(pq.cp, "seed"):
        pq.cp.seed = seed
    t0 = time.time()
    pq.train(E)
    codes = pq.compute_codes(E)
    cb = faiss.vector_to_array(pq.centroids).reshape(m, 1 << nbits, d // m)
    cb = np.ascontiguousarray(cb, dtype=np.float32)
    mse = float(((pq.decode(codes) - E) ** 2).sum(axis=1).mean())
    return cb, codes, mse, time.time() - t0


def pq_mse(E, cb, codes):
    """Sai số tái tạo của một codebook đã có, để so với bản dựng lại."""
    m = cb.shape[0]
    rec = np.concatenate([cb[j][codes[:, j]] for j in range(m)], axis=1)
    return float(((rec - E) ** 2).sum(axis=1).mean())


# --------------------------------------------------------------- encoders
def torch_setup():
    import torch
    n = int(os.environ.get("PREP_THREADS", os.cpu_count() or 1))
    torch.set_num_threads(n)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    return torch, dev, n


def lib_versions():
    out = {"python": sys.version.split()[0], "numpy": np.__version__}
    for mod in ("torch", "transformers", "sentence_transformers", "faiss",
                "pandas", "pyarrow", "huggingface_hub", "datasets"):
        try:
            m = __import__(mod)
            out[mod] = getattr(m, "__version__", "?")
        except Exception as e:  # noqa: BLE001
            out[mod] = f"không có ({type(e).__name__})"
    return out


def encode_chunked(encode_fn, texts, cache_dir, chunk=1000, label=""):
    """Encode theo khối, lưu từng khối để chạy lại thì tiếp tục từ chỗ dừng.

    encode_fn(list_of_texts) -> np.ndarray (n, d) float32, đã chuẩn hoá.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    n = len(texts)
    parts = []
    t_start = time.time()
    done_new = 0
    for s in range(0, n, chunk):
        e = min(n, s + chunk)
        fp = cache_dir / f"part_{s:07d}_{e:07d}.npy"
        if fp.exists():
            arr = np.load(fp)
            if arr.shape[0] == e - s:
                parts.append(arr)
                continue
        t0 = time.time()
        arr = np.ascontiguousarray(encode_fn(texts[s:e]), dtype=np.float32)
        if arr.shape[0] != e - s:
            die(f"{label}: khối {s}-{e} trả về {arr.shape[0]} vector")
        save_npy(arr, fp)
        parts.append(arr)
        done_new += e - s
        rate = done_new / max(1e-9, time.time() - t_start)
        left = n - e
        log(f"{label}: {e:,}/{n:,} ({(e - s) / max(1e-9, time.time() - t0):.1f} văn bản/giây; "
            f"còn khoảng {left / max(rate, 1e-9) / 60:.0f} phút)")
    return np.ascontiguousarray(np.concatenate(parts, axis=0), dtype=np.float32)


def save_dataset(name, Ec, Eq, corpus_texts, gt, pq_list, target_dir=DATA):
    """Ghi bộ dữ liệu theo đúng tên file mà simulator đọc (xem prepare/README.md).

    pq_list: danh sách (m, codebook, codes). Hậu tố file là _m{m}.
    """
    target_dir = Path(target_dir)
    p = lambda s: target_dir / f"{name}_{s}"  # noqa: E731
    save_npy(Ec, p("corpus_embeddings.npy"))
    save_npy(Eq, p("query_embeddings.npy"))
    for m, cb, codes in pq_list:
        save_npy(cb, p(f"pq_codebook_m{m}.npy"))
        save_npy(codes, p(f"pq_codes_m{m}.npy"))
    if corpus_texts is not None:
        save_json([str(x) for x in corpus_texts], p("corpus_texts.json"))
    save_json(gt, p("ground_truth.json"), indent=2)


def update_manifest(entry):
    """Ghi vào data/manifest_r1.json (không đụng data/manifest.json đang được git theo dõi)."""
    path = DATA / "manifest_r1.json"
    mf = load_json(path) if path.exists() else []
    mf = [x for x in mf if x.get("name") != entry["name"]]
    mf.append(entry)
    save_json(mf, path, indent=2)
