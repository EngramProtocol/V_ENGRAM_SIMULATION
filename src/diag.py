"""Chẩn đoán pha dựng mạng và ingest (ppna-r1, mục 2.3 của tài liệu sửa bài).

Hai câu hỏi:
  1. Record được đặt đúng tại r peer XOR-gần nhất toàn cục bao nhiêu phần trăm,
     và thứ hạng XOR toàn cục của anchor đã chọn là bao nhiêu.
  2. Bảng định tuyến dựng lúc join chứa bao nhiêu trong `near` peer XOR-gần
     nhất thật của mỗi peer.

Chỉ đọc trạng thái mạng, không dùng số ngẫu nhiên, không sửa gì, nên gọi hay
không gọi đều không đổi kết quả mô phỏng.

So khoảng cách bằng 64 bit cao của ID 160 bit. Thứ tự XOR theo 64 bit cao
trùng thứ tự theo 160 bit trừ khi hai peer trùng nguyên 64 bit cao, điều gần như
không xảy ra với 10^4 ID ngẫu nhiên (xác suất cỡ N^2 / 2^65).
"""
import numpy as np

_U64MAX = np.iinfo(np.uint64).max


def _hi64(x):
    return (x >> 96) & 0xFFFFFFFFFFFFFFFF


def build_diagnostics(nodes, ingest_log, r, near=20, chunk=512):
    ids = [n.node_id for n in nodes]
    pos = {nid: j for j, nid in enumerate(ids)}
    hi = np.array([_hi64(i) for i in ids], dtype=np.uint64)
    n_nodes = len(ids)
    out = {}

    # ---- 1. bảng định tuyến so với near peer XOR-gần nhất thật ----
    contacts = []
    for n in nodes:
        src = [p for b in n.kbuckets.values() for p in b] if n.kbuckets else n.routing_table
        contacts.append({pos[p.node_id] for p in src if p.node_id in pos})
    sizes = np.array([len(c) for c in contacts], dtype=float)
    kk = min(near, n_nodes - 1)
    cover = np.zeros(n_nodes)
    for a in range(0, n_nodes, chunk):
        D = hi[a:a + chunk, None] ^ hi[None, :]
        rows = np.arange(D.shape[0])
        D[rows, a + rows] = _U64MAX                     # bỏ chính nó
        nn = np.argpartition(D, kk - 1, axis=1)[:, :kk]
        for ri in range(D.shape[0]):
            c = contacts[a + ri]
            cover[a + ri] = sum(1 for j in nn[ri] if int(j) in c) / kk
    out["overlay_contacts_mean"] = float(sizes.mean())
    out["overlay_contacts_min"] = int(sizes.min())
    out[f"overlay_near{kk}_frac"] = float(cover.mean())

    # ---- 2. vị trí record so với r peer XOR-gần nhất thật ----
    if ingest_log:
        keys = np.array([_hi64(k) for k, _ in ingest_log], dtype=np.uint64)
        exact = 0
        ranks = []
        n_short = 0
        for a in range(0, len(keys), chunk):
            D = keys[a:a + chunk, None] ^ hi[None, :]    # (b, N)
            b = D.shape[0]
            rr = min(r, n_nodes)
            true_r = np.argpartition(D, rr - 1, axis=1)[:, :rr]
            for ri in range(b):
                anc = [pos[x] for x in ingest_log[a + ri][1] if x in pos]
                if len(anc) < rr:
                    n_short += 1
                if set(anc) == set(int(j) for j in true_r[ri]):
                    exact += 1
                if anc:
                    da = D[ri, anc]
                    ranks.extend(int((D[ri] < d).sum()) for d in da)
        ranks = np.array(ranks, dtype=float)
        out["placement_keys"] = int(len(keys))
        out["placement_exact_frac"] = exact / len(keys)
        out["placement_rank_mean"] = float(ranks.mean()) if len(ranks) else None
        out["placement_rank_p90"] = float(np.percentile(ranks, 90)) if len(ranks) else None
        out["placement_rank_max"] = int(ranks.max()) if len(ranks) else None
        out["placement_short"] = int(n_short)
    return out
