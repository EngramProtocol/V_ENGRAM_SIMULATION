"""Thành phần oracle cho phép phân tách khoảng cách giữa hai mô hình (ppna-r1 đợt 2).

Ba công tắc của mô hình iterative:
  đặt record    lookup Ripple Search (thật) hoặc r peer XOR-gần nhất thật (oracle)
  bảng định tuyến dựng bằng join (thật) hoặc đầy đủ từ thông tin toàn cục (oracle)
  truy vấn      Ripple Search (thật) hoặc đúng K peer XOR-gần nhất thật (oracle)

Module này chỉ đọc ID peer và dùng bộ sinh số ngẫu nhiên riêng (numpy RandomState do
người gọi truyền vào), không đụng tới random của Python, nên không làm lệch dòng số
ngẫu nhiên của phần mô phỏng.

So khoảng cách bằng 64 bit cao trước rồi xét lại bằng ID 160 bit đầy đủ ở các vị trí
hoà, nên kết quả đúng tuyệt đối theo XOR 160 bit.
"""
import numpy as np

_MASK64 = (1 << 64) - 1


def _hi64(x):
    return (x >> 96) & _MASK64


class XorIndex:
    """Chỉ mục XOR trên một tập peer (thường là các peer còn sống)."""

    def __init__(self, nodes):
        self.nodes = list(nodes)
        self.ids = [n.node_id for n in self.nodes]
        self.hi = np.array([_hi64(i) for i in self.ids], dtype=np.uint64)
        self.pos = {nid: j for j, nid in enumerate(self.ids)}

    def __len__(self):
        return len(self.nodes)

    def _dist(self, key):
        return self.hi ^ np.uint64(_hi64(key))

    def closest(self, key, k):
        """k peer XOR-gần key nhất, theo thứ tự khoảng cách tăng dần."""
        n = len(self.nodes)
        k = min(int(k), n)
        if k <= 0:
            return []
        d = self._dist(key)
        idx = np.argpartition(d, k - 1)[:k]
        thr = d[idx].max()
        cand = np.flatnonzero(d <= thr).tolist()        # gồm cả các vị trí hoà ở 64 bit cao
        cand.sort(key=lambda j: self.ids[j] ^ key)
        return [self.nodes[j] for j in cand[:k]]

    def ranks(self, key, nodes):
        """Thứ hạng XOR toàn cục (0 = gần nhất) của từng peer trong nodes."""
        if not nodes:
            return []
        d = self._dist(key)
        js = np.array([self.pos[nd.node_id] for nd in nodes])
        dv = d[js]
        r = (d[None, :] < dv[:, None]).sum(axis=1)
        eq = (d[None, :] == dv[:, None]).sum(axis=1)
        out = [int(x) for x in r]
        for t in np.flatnonzero(eq > 1).tolist():       # hoà ở 64 bit cao: so đủ 160 bit
            full = nodes[t].node_id ^ key
            ties = np.flatnonzero(d == dv[t]).tolist()
            out[t] += sum(1 for j in ties if (self.ids[j] ^ key) < full)
        return out


def _bit_length_u64(x):
    """bit_length của từng phần tử uint64 (0 cho 0), tính đúng bằng phép dịch."""
    x = x.copy()
    n = np.zeros(x.shape, dtype=np.int64)
    for s in (32, 16, 8, 4, 2, 1):
        m = x >= (np.uint64(1) << np.uint64(s))
        n[m] += s
        x[m] >>= np.uint64(s)
    n[x > 0] += 1
    return n


def build_full_tables(nodes, k_bucket, rng):
    """Bảng định tuyến đầy đủ từ thông tin toàn cục: bucket i của peer u giữ
    min(k_bucket, số peer có khoảng cách XOR trong [2^i, 2^(i+1))) peer, chọn đều
    ngẫu nhiên bằng rng. Thay kbuckets và routing_table của mọi peer.

    Trả về thống kê: số contact trung bình, nhỏ nhất, lớn nhất."""
    nodes = list(nodes)
    ids = [n.node_id for n in nodes]
    hi = np.array([_hi64(i) for i in ids], dtype=np.uint64)
    n = len(nodes)
    sizes = []
    for u in range(n):
        x = hi ^ hi[u]
        bl = _bit_length_u64(x)                         # bit_length của 64 bit cao
        # bucket theo 160 bit: i = 96 + bit_length(hi) - 1 khi 64 bit cao khác nhau;
        # trùng 64 bit cao (gần như không xảy ra) thì tính đủ 160 bit
        bidx = bl + 95
        same = np.flatnonzero(x == 0).tolist()
        for j in same:
            if j != u:
                bidx[j] = (ids[j] ^ ids[u]).bit_length() - 1
        bidx[u] = -1
        order = rng.permutation(n)
        order = order[order != u]
        order = order[np.argsort(bidx[order], kind="stable")]
        bo = bidx[order]
        starts = np.flatnonzero(np.r_[True, bo[1:] != bo[:-1]])
        kb = {}
        for a, s in enumerate(starts):
            e = starts[a + 1] if a + 1 < len(starts) else len(order)
            kb[int(bo[s])] = [nodes[j] for j in order[s:min(e, s + k_bucket)].tolist()]
        node = nodes[u]
        node.kbuckets = kb
        node.routing_table = set(p for b in kb.values() for p in b)
        sizes.append(len(node.routing_table))
    return {"contacts_mean": float(np.mean(sizes)), "contacts_min": int(min(sizes)),
            "contacts_max": int(max(sizes))}


def save_routing_state(nodes):
    return [({i: list(b) for i, b in n.kbuckets.items()}, set(n.routing_table)) for n in nodes]


def restore_routing_state(nodes, state):
    for n, (kb, rt) in zip(nodes, state):
        n.kbuckets = {i: list(b) for i, b in kb.items()}
        n.routing_table = set(rt)


def remove_dead(nodes, dead):
    """Mất peer tĩnh như main_churn_test.kill_random_nodes: peer chết biến khỏi
    routing_table và k-bucket của mọi peer còn sống; record trên peer chết mất theo
    vì không còn ai định tuyến tới nó. Trả danh sách peer còn sống (giữ thứ tự)."""
    live = [n for n in nodes if n not in dead]
    for n in live:
        n.routing_table.difference_update(dead)
        if n.kbuckets:
            for i, b in n.kbuckets.items():
                n.kbuckets[i] = [p for p in b if p not in dead]
    return live
