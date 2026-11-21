"""Đợt 5 (ppna-r1-dot5): churn trên mô hình iterative, cho Bảng 10.

Bảng 10 hiện chỉ có số của mô hình lý tưởng (main_churn_engine.py): mọi lookup trả đúng r hoặc K peer
XOR-gần nhất trong các peer đang sống, và peer vừa tham gia được mọi peer biết ngay. Script này chạy
cùng kịch bản churn trên giao thức của mô hình iterative:

- Mạng lúc t = 0 là mạng của các thí nghiệm iterative tĩnh với join đầy đủ (join tuần tự trên
  k-bucket, một vòng làm mới bucket, ingest bằng Ripple Search), dựng bằng ppna_r1/dot2/iterative.py.
- Phiên của peer: cùng phân bố và cùng dòng số ngẫu nhiên với mô hình lý tưởng (Weibull k = 0,5,
  median 120 phút; số peer không đổi: peer hết phiên rời đi, một peer mới với ID mới và bộ nhớ rỗng
  thế chỗ). Cùng seed thì peer rời mạng ở đúng các khe, đúng các epoch như mô hình lý tưởng.
- Peer rời đi mất record và bảng định tuyến. Peer khác vẫn giữ nó trong k-bucket cho tới khi phát hiện.
- Peer mới join đầy đủ như Kademlia gốc: liên lạc một peer bootstrap đang sống, tra chính ID mình (chỉ
  biết bootstrap), ping các peer tìm được, rồi làm mới mọi bucket xa hơn láng giềng gần nhất.
- Mọi RPC cập nhật k-bucket theo Kademlia: bên nhận học bên gửi, bên gửi làm mới bên trả lời; bucket
  đầy thì ping peer lâu nhất chưa thấy và chỉ thay khi peer đó không trả lời. RPC tới peer đã rời mạng
  hết giờ (vẫn tính một RPC) và bên gửi xoá peer đó khỏi bucket.
- Làm mới định kỳ: mỗi peer tra chính ID mình mỗi --refresh-every phút (mặc định 60, như chu kỳ làm mới
  một giờ của Kademlia), lệch pha đều giữa các peer. Bucket xa được giữ mới bằng lưu lượng.
- Sửa chữa lazy như mô hình lý tưởng: đủ L*r anchor còn giữ record thì gia hạn TTL, thiếu thì neo lại
  cả L khoá. Neo lại bằng lookup Ripple Search (cùng quy tắc với ingest) từ một peer đang sống và STORE
  tới r peer gần nhất còn trả lời. TTL = 2,2 chu kỳ sửa; record hết hạn bị xoá.
- Đo cùng lịch và cùng pha với mô hình lý tưởng: meta vật lý (anchor còn giữ record), meta định tuyến
  được (lookup Ripple Search tới từng khoá của cùng 500 object lấy mẫu; có peer trả về nào giữ record
  không), R@5 của 200 query chạy đúng đường đọc iterative (Ripple Search L = 5, T = 8, K = 20, c = 16,
  ADC, kappa = 30), số bản sống, message sửa chữa. Lúc đo, lookup và RPC không cập nhật k-bucket, để
  phép đo không đổi trạng thái mạng.
- Đường đọc dưới churn: client gửi yêu cầu tới K peer đầu của kết quả lookup; peer nào đã rời mạng thì
  hết giờ (tính một RPC) và client gửi tiếp cho ứng viên kế tiếp, tới khi đủ K peer trả lời. Khi mọi peer
  sống, việc này trùng đúng đường đọc của mô hình tĩnh. Mỗi lần đo cũng tính R@5 của client không thay
  peer hết giờ, trên đúng các lookup đó (độ nhạy, ghép cặp theo query).
- Thêm một lần đo trước warm-up (mạng lúc t = 0). Với cùng seed, R@5 từng query của lần đo này phải trùng
  biến thể base của mô hình iterative tĩnh, join đầy đủ, trên 200 query đầu (kiểm trong README_dot5.md).

Chạy từ gốc repo:
  python3 ppna_r1/dot5/churn_iter.py --dataset code --nodes 10000 --nq 200 --median-session 120 \\
      --duration 1440 --meta-anchors 1 --repair-interval 480 --seed 1 --out f.json

Job dài ghi checkpoint mỗi --ckpt-every giây vào <out>.ckpt (và khi nhận SIGTERM, ở mốc epoch kế tiếp);
chạy lại đúng lệnh thì chạy tiếp từ checkpoint, và kết quả trùng với lần chạy liền một mạch (chỉ khác các
trường thời gian).
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_iterative():
    p = os.path.join(_HERE, '..', 'dot2', 'iterative.py')
    spec = importlib.util.spec_from_file_location('ppna_iterative', p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# đặt BASE_ENV của mô hình iterative (L = 5, k-bucket, join, stable/all, R_max 15, ...) rồi import src.*
IT = _load_iterative()

import argparse      # noqa: E402
import bisect        # noqa: E402
import collections   # noqa: E402
import json          # noqa: E402
import pickle        # noqa: E402
import random        # noqa: E402
import signal        # noqa: E402
import time          # noqa: E402
from types import SimpleNamespace  # noqa: E402

import numpy as np   # noqa: E402
import simpy         # noqa: E402

from src.diag import build_diagnostics  # noqa: E402
from src.node import VEngramNode, adc_lut   # noqa: E402

rt = IT.rt
netmod = IT.netmod

K_BUCKET = int(os.environ['K_BUCKET'])
ALPHA = rt.DEFAULT_ALPHA
# cấu hình truy vấn chính, như run_variant mặc định của iterative.py và như mô hình lý tưởng
K_QUERY, T_PROBE, C_BITS = 20, 8, 16
TTL_INF = float('inf')
CKPT_VERSION = 1

# Bộ đếm RPC theo loại. Tiền tố: join (peer mới), refresh (làm mới định kỳ), repair (sửa chữa),
# meas_route và meas_query (đo).
STATS = collections.Counter()
# SIGTERM (bộ chạy dừng job): ghi checkpoint ở mốc epoch kế tiếp rồi thoát với mã 75
STOP = {'flag': False}


# ------------------------------------------------------------------ k-bucket dưới churn
def _bidx(a, b):
    return (a.node_id ^ b.node_id).bit_length() - 1


def kb_add(node, peer):
    """node nhận tin từ peer: cập nhật k-bucket như Kademlia (Maymounkov và Mazières 2002, mục 2.2).
    Đã có thì đưa về cuối (mới thấy nhất). Bucket còn chỗ thì thêm. Bucket đầy thì ping peer lâu nhất
    chưa thấy: nó trả lời thì giữ nó (đưa về cuối) và bỏ peer mới; không trả lời thì thay bằng peer mới."""
    i = _bidx(node, peer)
    b = node.kbuckets.get(i)
    if b is None:
        node.kbuckets[i] = [peer]
        return
    for j, p in enumerate(b):
        if p is peer:
            del b[j]
            b.append(peer)
            return
    if len(b) < K_BUCKET:
        b.append(peer)
        return
    lru = b.pop(0)
    STATS['ping_rpcs'] += 1
    if lru.alive:
        b.append(lru)
    else:
        STATS['ping_timeouts'] += 1
        b.append(peer)


def evict(node, peer):
    """peer không trả lời RPC của node: node xoá peer khỏi bucket."""
    b = node.kbuckets.get(_bidx(node, peer))
    if b:
        for j, p in enumerate(b):
            if p is peer:
                del b[j]
                STATS['evictions'] += 1
                return


def touch(sender, peer):
    """sender gửi RPC và peer trả lời: peer học sender, sender làm mới peer."""
    if sender is peer:
        return
    kb_add(peer, sender)
    kb_add(sender, peer)


def kb_closest(node, key, k):
    """k contact XOR-gần key nhất trong bảng của node: cùng kết quả và cùng thứ tự với
    VEngramNode.kb_closest (sắp xếp mọi contact), nhưng chỉ sắp xếp các bucket cần. Với t là bit cao
    nhất của node ^ key: contact ở bucket t gần key hơn mọi contact khác; contact ở các bucket j < t
    cách key trong [2^t, 2^(t+1)); contact ở bucket j > t cách key trong [2^j, 2^(j+1))."""
    kb = node.kbuckets
    t = (node.node_id ^ key).bit_length() - 1
    out = []
    b = kb.get(t)
    if b:
        out = sorted(b, key=lambda p: p.node_id ^ key)
        if len(out) >= k:
            return out[:k]
    low = [p for j, bb in kb.items() if j < t for p in bb]
    if low:
        low.sort(key=lambda p: p.node_id ^ key)
        out.extend(low)
        if len(out) >= k:
            return out[:k]
    for j in sorted(j for j in kb if j > t):
        bb = kb[j]
        if bb:
            out.extend(sorted(bb, key=lambda p: p.node_id ^ key))
            if len(out) >= k:
                return out[:k]
    return out


def lookup(key, start, k, phase=None, sender=None, learn=False, cat='meas_query', init=None,
           alpha=ALPHA, max_rounds=None):
    """Ripple Search cho một khoá, đúng thuật toán của rt.iterative_find_k_closest_nodes (giữ danh sách
    ứng viên đã xếp thay vì xếp lại mỗi vòng; cùng kết quả), trên mạng có peer đã rời đi. Peer đã rời đi
    không trả lời: RPC tới nó vẫn tính, nó không mở rộng ứng viên và bị loại khỏi kết quả; learn=True thì
    sender xoá nó khỏi bucket và mọi peer trả lời học sender.
    init: tập ứng viên ban đầu (mặc định start và mọi contact của start).
    Trả (ứng viên xếp theo XOR, không gồm peer đã biết là chết; tập peer đã hỏi; số RPC; số vòng)."""
    stop_rule, scope, rmax = rt.phase_rules(phase)
    if max_rounds is None:
        max_rounds = rmax
    if init is None:
        cand = {start}
        for b in start.kbuckets.values():
            cand.update(b)
    else:
        cand = set(init)
    dl = sorted([(n.node_id ^ key, n) for n in cand], key=_first)
    queried = set()
    dead = set()
    prev = None
    hops = rpcs = tmo = 0
    stable = stop_rule == 'stable'
    for _ in range(max_rounds):
        to_query = []
        for _d, n in (dl if scope == 'all' else dl[:k]):
            if n not in queried:
                to_query.append(n)
                if len(to_query) == alpha:
                    break
        if not to_query:
            break
        best = tuple(d for d, _n in dl[:k]) if stable else None
        hops += 1
        new = []
        died = False
        for n in to_query:
            queried.add(n)
            rpcs += 1
            if not n.alive:
                tmo += 1
                dead.add(n)
                died = True
                if learn:
                    evict(sender, n)
                continue
            if n.kbuckets:
                for p in kb_closest(n, key, k):      # trả lời trước, rồi mới học bên gửi
                    if p not in cand and p not in dead:
                        cand.add(p)
                        new.append(p)
            if learn:
                touch(sender, n)
        if died:
            cand.difference_update(dead)
            dl = [x for x in dl if x[1] not in dead]
        for p in new:
            if p in cand:
                bisect.insort(dl, (p.node_id ^ key, p), key=_first)
        if stable:
            if best == prev:
                break
            prev = best
    STATS[cat + '_lookups'] += 1
    STATS[cat + '_rpcs'] += rpcs
    STATS[cat + '_timeouts'] += tmo
    STATS[cat + '_rounds'] += hops
    return [n for _d, n in dl], queried, rpcs, hops


def _first(x):
    return x[0]


# Ghi chép của query đang đo (measure_queries đặt lại trước mỗi query): peer đã rời mạng mà client đã
# thử (mỗi peer tính một RPC hết giờ, một lần mỗi query) và các peer còn sống nằm trong k vị trí đầu của
# kết quả lookup (để tính R@5 của client không thay peer, trên đúng các lookup đó).
QREC = {'on': False, 'dead': set(), 'primary': set(), 'timeouts': 0}


def first_live(ordered, k):
    """k peer đầu tiên còn trả lời trong danh sách ứng viên đã xếp, và các peer đã rời mạng đứng trước
    chúng: client gửi yêu cầu tới k peer đầu, peer nào hết giờ thì gửi tiếp cho ứng viên kế tiếp."""
    out, dead = [], []
    for n in ordered:
        if len(out) == k:
            break
        if n.alive:
            out.append(n)
        else:
            dead.append(n)
    return out, dead


def _query_lookup(key, bootstrap_node, alpha=ALPHA, k=20, max_rounds=None, phase=None):
    """Thay rt.iterative_find_k_closest_nodes trong đường đọc (src.network) lúc đo: chỉ đọc. Trả k peer
    còn trả lời đầu tiên của danh sách ứng viên (peer hết giờ được thay bằng ứng viên kế tiếp; khi mọi peer
    sống thì đúng là ordered[:k] như mô hình tĩnh)."""
    ordered, _q, rpcs, hops = lookup(key, bootstrap_node, k, phase=phase, cat='meas_query',
                                     alpha=alpha, max_rounds=max_rounds)
    out, dead = first_live(ordered, k)
    if QREC['on']:
        for n in dead:
            if n not in QREC['dead']:
                QREC['dead'].add(n)
                QREC['timeouts'] += 1
        QREC['primary'].update(n for n in ordered[:k] if n.alive)
    return out, hops, rpcs


def ping_found(node, found, queried, cat):
    """Như bước join của mô hình tĩnh (peer mới và các peer tìm được học nhau): peer mới ping những peer
    trong kết quả lookup mà nó chưa hỏi; peer trả lời thì hai bên học nhau."""
    for p in found:
        if p is node or p in queried:
            continue
        STATS[cat + '_ping_rpcs'] += 1
        if p.alive:
            touch(node, p)
        else:
            STATS[cat + '_ping_timeouts'] += 1


def join_new(node, boot, rng_ref):
    """Join đầy đủ của một peer mới (như bootstrap_network rồi refresh_buckets cho riêng peer này)."""
    STATS['join_hello_rpcs'] += 1
    touch(node, boot)
    found, queried, _r, _h = lookup(node.node_id, boot, K_BUCKET, phase='join', sender=node,
                                    learn=True, cat='join', init=[boot])
    ping_found(node, found[:K_BUCKET], queried, 'join')
    contacts = [p for b in node.kbuckets.values() for p in b]
    if not contacts:
        return
    nearest = min(contacts, key=lambda p: p.node_id ^ node.node_id)
    b0 = _bidx(node, nearest)
    for i in range(b0 + 1, 160):
        low = int.from_bytes(rng_ref.bytes(20), 'big') & ((1 << i) - 1)
        target = node.node_id ^ ((1 << i) | low)
        found, queried, _r, _h = lookup(target, node, K_BUCKET, phase='refresh', sender=node,
                                        learn=True, cat='join')
        ping_found(node, found[:K_BUCKET], queried, 'join')


def self_refresh(node):
    """Làm mới định kỳ: peer tra chính ID mình (bước join của Kademlia, mà các bản cài đặt như libp2p
    lặp lại mỗi chu kỳ làm mới bảng định tuyến). Contact gần nó không trả lời bị xoá khỏi bucket, peer gần
    mới tham gia được học. Bucket xa được giữ mới bằng lưu lượng (học bên gửi, ping peer cũ nhất khi đầy)."""
    found, queried, _r, _h = lookup(node.node_id, node, K_BUCKET, phase='refresh', sender=node,
                                    learn=True, cat='refresh')
    ping_found(node, found[:K_BUCKET], queried, 'refresh')


def depart(n):
    n.alive = False
    n.RAM_Index.clear()
    n.EXP.clear()
    n.kbuckets = {}


# ------------------------------------------------------------------ mô phỏng
class ChurnSim:
    def __init__(self, a, cfg, data):
        self.a = a
        self.cfg = cfg
        self.seed = a.seed
        self.N = a.nodes
        self.L = int(os.environ['NUM_TABLES'])
        self.r = a.meta_anchors
        self.rep = a.repair_interval
        self.ttl = cfg['ttl']
        self.epoch = cfg['epoch']
        self.n_warm = cfg['warmup_epochs']
        self.n_epoch = cfg['n_epoch']
        self.data = data
        self.n_docs = data['n_docs']
        self.tags = [f'doc_{i}' for i in range(self.n_docs)]
        self.meas_eps = measure_epochs(a.seed, self.n_epoch, cfg['measure_every'], self.rep, self.epoch)
        # phiên: đúng dòng số của ChurnNetwork (main_churn_engine.py)
        self.shape = a.weibull_shape
        self.scale = a.median_session / (np.log(2) ** (1.0 / self.shape))
        self.rng = np.random.RandomState(a.seed)
        self.remaining = self.scale * self.rng.weibull(self.shape, size=self.N)
        # các dòng số riêng của mô hình iterative
        self.rng_id = random.Random(a.seed + 5101)          # ID 160 bit của peer mới
        self.rng_boot = random.Random(a.seed + 5202)        # peer bootstrap của peer mới
        self.rng_ref = np.random.RandomState((a.seed * 104729 + 5303) % (2 ** 32))  # làm mới bucket
        self.rng_rep = random.Random(a.seed + 5404)         # peer khởi phát lookup neo lại
        self.rnd_route = random.Random(a.seed + 777)        # baseline ngẫu nhiên, như mô hình lý tưởng
        # làm mới định kỳ: mỗi epoch, peer có uid % refresh_k == (số epoch đã chạy) % refresh_k tra chính mình
        self.refresh_k = int(round(a.refresh_every / self.epoch)) if a.refresh_every > 0 else 0
        self.n_steps = 0
        self.now = 0.0
        self.total_departures = 0
        self.repair_msgs = 0
        self.n_reanchored = 0
        self.n_repairs = 0
        self.exp_pending = set()
        self.stage = 'warmup'
        self.ep_w = 0
        self.wsince = 0.0
        self.ep = 0
        self.since_repair = 0.0
        self.dep0 = 0
        self.msg0 = 0
        self.stats0 = {}
        self.hist = []
        self.pre = None
        self.build_info = {}
        self.timing = collections.Counter()
        self.n_resumed = 0
        self.slots = []
        self.anchors = []
        self.next_uid = 0

    # ---------------- dựng mạng lúc t = 0
    def build(self, ctx, info):
        exp0 = TTL_INF if self.rep <= 0 else self.ttl
        self.slots = list(ctx.nodes)
        for i, n in enumerate(self.slots):
            n.uid = i
            n.alive = True
            n.env = None
            n.routing_table = set()           # không dùng dưới churn: lookup đọc thẳng k-bucket
            n.EXP = {t: exp0 for t in n.RAM_Index}
        self.next_uid = len(self.slots)
        if exp0 != TTL_INF:
            self.exp_pending.add(exp0)
        by_id = {n.node_id: n for n in self.slots}
        log = netmod.INGEST_LOG
        if len(log) != self.n_docs * self.L:
            raise SystemExit(f'INGEST_LOG có {len(log)} mục, cần {self.n_docs * self.L} (DIAG_BUILD=1?)')
        self.anchors = []
        for i in range(self.n_docs):
            ent = log[i * self.L:(i + 1) * self.L]
            if [k for k, _ in ent] != self.data['keys'][i]:
                raise SystemExit(f'khoá ngữ nghĩa của doc {i} khác lúc ingest')
            self.anchors.append([by_id[x] for _k, ids in ent for x in ids])
        self.build_info = info

    def new_node(self):
        m = VEngramNode(None, self.rng_id.getrandbits(160))
        m.alive = True
        m.EXP = {}
        m.uid = self.next_uid
        m.joined_step = self.n_steps
        self.next_uid += 1
        return m

    # ---------------- động học
    def purge(self):
        """Xoá record hết hạn (main_churn_engine.ChurnNetwork.purge_expired). Chỉ quét khi có record
        tới hạn: hạn dùng chỉ sinh lúc ingest và lúc sửa, nên kết quả như quét mỗi epoch."""
        if not self.exp_pending or min(self.exp_pending) > self.now:
            return
        n = 0
        for nd in self.slots:
            E = nd.EXP
            if not E:
                continue
            gone = [t for t, e in E.items() if e <= self.now]
            for t in gone:
                del E[t]
                del nd.RAM_Index[t]
            n += len(gone)
        self.exp_pending = {e for e in self.exp_pending if e > self.now}
        STATS['purged'] += n

    def step(self):
        """Như ChurnNetwork.step: tiến một epoch, xoá record hết hạn, peer hết phiên rời đi và peer mới
        (ID mới, bộ nhớ rỗng) thế chỗ, rồi join đầy đủ, lần lượt theo thứ tự khe."""
        self.now += self.epoch
        self.purge()
        self.remaining -= self.epoch
        dead = np.flatnonzero(self.remaining <= 0)
        if len(dead):
            for i in dead:
                depart(self.slots[i])
            pending = set(int(i) for i in dead)
            for i in dead:
                i = int(i)
                m = self.new_node()
                while True:
                    j = self.rng_boot.randrange(self.N)
                    if j not in pending:
                        break
                boot = self.slots[j]
                self.slots[i] = m
                join_new(m, boot, self.rng_ref)
                pending.discard(i)
            self.remaining[dead] = self.scale * self.rng.weibull(self.shape, size=len(dead))
            self.total_departures += len(dead)
        if self.refresh_k:
            ph = self.n_steps % self.refresh_k
            for n in self.slots:
                if n.uid % self.refresh_k == ph and getattr(n, 'joined_step', -1) != self.n_steps:
                    self_refresh(n)
        self.n_steps += 1
        return len(dead)

    def repair(self):
        """Sửa lazy như main_churn_engine.repair, trên giao thức iterative."""
        exp = self.now + self.ttl
        need = self.L * self.r
        msgs = 0
        codes = self.data['codes']
        for i in range(self.n_docs):
            tag = self.tags[i]
            cur = self.anchors[i]
            STATS['repair_keepalive_rpcs'] += len(cur)
            alive = []
            for n in cur:
                if not n.alive:
                    STATS['repair_keepalive_timeouts'] += 1
                elif tag in n.RAM_Index:
                    alive.append(n)
            if len(alive) >= need:
                for n in alive:
                    n.EXP[tag] = exp
                    msgs += 1
                continue
            new = []
            for skey in self.data['keys'][i]:
                origin = self.slots[self.rng_rep.randrange(self.N)]
                ordered, _q, _r, _h = lookup(skey, origin, self.r, phase='ingest', sender=origin,
                                             learn=True, cat='repair')
                placed = 0
                for n in ordered:
                    if placed >= self.r:
                        break
                    STATS['repair_store_rpcs'] += 1
                    if not n.alive:
                        STATS['repair_store_timeouts'] += 1
                        evict(origin, n)
                        continue
                    touch(origin, n)
                    if tag not in n.RAM_Index:
                        n.RAM_Index[tag] = codes[i]
                    n.EXP[tag] = exp
                    msgs += 1
                    new.append(n)
                    placed += 1
                if placed < self.r:
                    STATS['repair_short'] += 1
            self.anchors[i] = new
            self.n_reanchored += 1
        self.exp_pending.add(exp)
        self.repair_msgs += msgs
        self.n_repairs += 1

    # ---------------- đo
    def measure_queries(self):
        d = self.data
        live = self.slots
        by_id = {n.node_id: n for n in live}
        n_touch = min(K_QUERY * self.L * T_PROBE, self.N)
        acc = {'hits': [], 'hits_noreplace': [], 'reach': [], 'rand': [], 'rpcs': [], 'rounds': [],
               'contacted': [], 'eval_timeouts': [], 'dead_eval': []}
        env = simpy.Environment()
        cb = d['codebook']

        def _loop(env):
            for qi, item in enumerate(d['gt'][:d['nq']]):
                qv = d['Q'][item['query_id'] - 1]
                col = {}
                QREC.update(on=True, dead=set(), primary=set(), timeouts=0)
                retrieved, _h, _u, st = yield env.process(netmod.query_pipeline_process(
                    env, live, qv, cb, target_k=IT.TARGET_K, k_query=K_QUERY,
                    multi_probe=T_PROBE, random_routing=False, verbose=False, probe_bits=C_BITS,
                    mode='semantic', live_nodes=live, collect=col))
                QREC['on'] = False
                gt5 = {g['index'] for g in item['top_5_results'][:5]}
                acc['hits'].append(len({int(t.split('_')[1]) for t in retrieved[:5]} & gt5))
                # client không thay peer hết giờ, trên đúng các lookup này: chỉ các peer sống nằm trong
                # k vị trí đầu được đánh giá (cùng kappa, cùng cách gộp như src.network)
                lut = adc_lut(qv, cb)
                best = {}
                for nd in sorted(QREC['primary'], key=lambda n: n.node_id):
                    for tag, dist in nd.adc_search(qv, cb, top_k=netmod.LOCAL_TOP_K, lut=lut):
                        if tag not in best or dist < best[tag]:
                            best[tag] = dist
                top = sorted(best.items(), key=lambda x: x[1])[:IT.TARGET_K]
                acc['hits_noreplace'].append(len({int(t.split('_')[1]) for t, _ in top[:5]} & gt5))
                reach = set()
                n_dead = 0
                for nid in col['contacted']:
                    nd = by_id.get(nid)
                    if nd is None:
                        n_dead += 1
                    else:
                        reach.update(nd.RAM_Index.keys())
                acc['reach'].append(len({int(t.split('_')[1]) for t in reach} & gt5))
                acc['dead_eval'].append(n_dead)
                acc['eval_timeouts'].append(QREC['timeouts'])
                acc['rpcs'].append(st['rpcs'] + QREC['timeouts'])
                acc['rounds'].append(st['rounds'])
                acc['contacted'].append(st['contacted_nodes'])
                rr = set()
                for j in self.rnd_route.sample(range(self.N), n_touch):
                    rr.update(live[j].RAM_Index.keys())
                acc['rand'].append(len({int(t.split('_')[1]) for t in rr} & gt5))

        env.process(_loop(env))
        env.run()
        netmod._PROBE_DIAG.clear()       # chẩn đoán từng query của src.network: không dùng, tránh phình bộ nhớ
        return acc

    def snapshot(self, ep, t, phase=None, label=None):
        t0 = time.time()
        c0 = dict(STATS)
        nd = self.n_docs
        alive_meta = sum(1 for i in range(nd)
                         if any(n.alive and self.tags[i] in n.RAM_Index for n in self.anchors[i]))
        # định tuyến được: cùng mẫu 500 object với mô hình lý tưởng, lookup Ripple Search tới từng khoá
        _rs = random.Random(self.seed + 991 + ep)
        sample = _rs.sample(range(nd), min(500, nd))
        _ro = random.Random(self.seed + 1991 + ep)
        reach = reach_raw = route_tmo = 0
        for i in sample:
            tag = self.tags[i]
            found = found_raw = False
            for skey in self.data['keys'][i]:
                origin = self.slots[_ro.randrange(self.N)]
                ordered, _q, _r, _h = lookup(skey, origin, K_QUERY, cat='meas_route')
                live_k, dead_k = first_live(ordered, K_QUERY)
                route_tmo += len(dead_k)
                found_raw = found_raw or any(n.alive and tag in n.RAM_Index for n in ordered[:K_QUERY])
                if any(tag in n.RAM_Index for n in live_k):
                    found = True
                    break
            reach += found
            reach_raw += found_raw
        routable = 100.0 * reach / len(sample)
        q = self.measure_queries()
        nq = len(q['hits'])
        fr = 100.0 * sum(q['hits']) / (5.0 * nq)
        fr_nr = 100.0 * sum(q['hits_noreplace']) / (5.0 * nq)
        rr = 100.0 * sum(q['reach']) / (5.0 * nq)
        rand = 100.0 * sum(q['rand']) / (5.0 * nq)
        tot = stale = near_tot = near_stale = 0
        for n in self.slots:
            for b in n.kbuckets.values():
                tot += len(b)
                stale += sum(1 for p in b if not p.alive)
            near = kb_closest(n, n.node_id, K_BUCKET)    # 20 contact gần chính nó nhất
            near_tot += len(near)
            near_stale += sum(1 for p in near if not p.alive)
        diag = build_diagnostics(self.slots, [], self.r)
        dc = {k: STATS.get(k, 0) - c0.get(k, 0) for k in STATS}
        row = {'epoch': ep, 't_min': round(t, 1), 'phase': phase,
               'meta_physical': 100.0 * alive_meta / nd, 'meta_routable': routable,
               # độ nhạy: client không thay peer hết giờ (cùng các lookup)
               'final_r5_noreplace': fr_nr, 'meta_routable_noreplace': 100.0 * reach_raw / len(sample),
               'meta_avail': 100.0 * alive_meta / nd,
               'reach_r5': rr, 'final_r5': fr, 'random_r5': rand,
               'ratio': (fr / rand) if rand > 0 else float('nan'),
               'nodes_touched': float(np.mean(q['contacted'])),
               'footprint': sum(len(n.RAM_Index) for n in self.slots) / nd,
               'departures': self.total_departures - self.dep0,
               'repair_msgs': self.repair_msgs - self.msg0,
               # riêng mô hình iterative
               'q_rpcs_mean': float(np.mean(q['rpcs'])), 'q_rounds_mean': float(np.mean(q['rounds'])),
               'q_lookup_timeouts_mean': dc.get('meas_query_timeouts', 0) / nq,
               'q_eval_timeouts_mean': float(np.mean(q['eval_timeouts'])),
               'q_dead_eval_mean': float(np.mean(q['dead_eval'])),
               'route_eval_timeouts_mean': route_tmo / max(1, dc.get('meas_route_lookups', 0)),
               'route_lookups': dc.get('meas_route_lookups', 0),
               'route_rpcs_mean': dc.get('meas_route_rpcs', 0) / max(1, dc.get('meas_route_lookups', 0)),
               'route_timeouts_mean': dc.get('meas_route_timeouts', 0) / max(1, dc.get('meas_route_lookups', 0)),
               'rt_contacts_mean': tot / self.N, 'rt_stale_frac': stale / max(1, tot),
               'rt_stale_near_frac': near_stale / max(1, near_tot),
               'rt_live_contacts_mean': diag['overlay_contacts_mean'],
               'rt_live_contacts_min': diag['overlay_contacts_min'],
               'rt_near20_frac': diag.get('overlay_near20_frac'),
               'n_reanchored': self.n_reanchored, 'n_repairs': self.n_repairs,
               'cum': {k: v - self.stats0.get(k, 0) for k, v in STATS.items()
                       if not k.startswith('meas_')},
               'per_query_hits5': q['hits'], 'per_query_hits5_noreplace': q['hits_noreplace'],
               'sec': round(time.time() - t0, 1)}
        if label:
            row['label'] = label
        print(f'    t={t:>6.0f}ph{"" if phase is None else f" pha{phase:.2f}"} | '
              f'phys {row["meta_physical"]:5.1f}% route {routable:5.1f}% | '
              f'R@5 {fr:5.1f}% (không thay peer {fr_nr:5.1f}%) rnd {rand:5.1f}% | vết {row["footprint"]:5.2f} | '
              f'msg {row["repair_msgs"]:>8,} | RPC/q {row["q_rpcs_mean"]:5.0f} | '
              f'contact chết {100 * row["rt_stale_frac"]:4.1f}% | {row["sec"]:.0f} giây', flush=True)
        return row

    # ---------------- vòng chính (theo main_churn_engine.main)
    def run(self, ckpt_path, ckpt_every):
        last = [time.time()]
        clock = [time.time()]

        def lap(key):
            t = time.time()
            self.timing[key] += t - clock[0]
            clock[0] = t

        def maybe_ckpt(force=False):
            if ckpt_path and (force or STOP['flag'] or time.time() - last[0] >= ckpt_every):
                t0 = time.time()
                self.save(ckpt_path)
                last[0] = clock[0] = time.time()
                print(f'    [checkpoint: {self.stage}, warm-up {self.ep_w}/{self.n_warm}, đo {self.ep}/{self.n_epoch}, '
                      f'{last[0] - t0:.1f} giây]', flush=True)
                if STOP['flag']:
                    print('[*] nhận SIGTERM: đã ghi checkpoint, thoát', flush=True)
                    sys.exit(75)

        def progress(label, done, total):
            if done % 12 == 0 or done == total:
                print(f'  {label} {done}/{total} epoch | {self.total_departures:,} lượt rời mạng | '
                      f'{self.n_repairs} vòng sửa | contact/peer {sum(len(b) for n in self.slots for b in n.kbuckets.values()) / self.N:.0f} '
                      f'| {time.strftime("%H:%M:%S")}', flush=True)

        if self.stage == 'warmup':
            while self.ep_w < self.n_warm:
                self.step()
                self.ep_w += 1
                self.wsince += self.epoch
                # sửa đúng theo chu kỳ trong warm-up, như mô hình lý tưởng
                if self.rep > 0 and self.wsince >= self.rep:
                    self.repair()
                    self.wsince = 0.0
                lap('warmup')
                progress('warm-up', self.ep_w, self.n_warm)
                if self.ep_w < self.n_warm:
                    maybe_ckpt()
            print(f'    {self.total_departures:,} lượt rời mạng trong warm-up', flush=True)
            self.stage = 'main0'
        if self.stage == 'main0':
            self.since_repair = 0.0
            self.dep0 = self.total_departures
            self.msg0 = self.repair_msgs
            self.stats0 = dict(STATS)
            self.hist.append(self.snapshot(0, 0.0, phase=0.0))
            lap('snapshots')
            self.stage = 'main'
            maybe_ckpt(force=True)
        while self.ep < self.n_epoch:
            self.ep += 1
            ep = self.ep
            self.step()
            self.since_repair += self.epoch
            just = False
            if self.rep > 0 and self.since_repair >= self.rep:
                self.repair()
                self.since_repair = 0.0
                just = True
            lap('main')
            progress('đo', ep, self.n_epoch)
            if ep in self.meas_eps:
                # pha = phần chu kỳ sửa đã trôi kể từ lần sửa gần nhất (0 = vừa sửa xong)
                ph = 0.0 if just else (self.since_repair / self.rep if self.rep > 0 else 1.0)
                self.hist.append(self.snapshot(ep, ep * self.epoch, phase=min(1.0, ph)))
                lap('snapshots')
            if self.ep < self.n_epoch:
                maybe_ckpt()
        self.stage = 'done'

    # ---------------- checkpoint
    def save(self, path):
        reg = {}
        for n in self.slots:
            reg.setdefault(n.uid, n)
            for b in n.kbuckets.values():
                for p in b:
                    reg.setdefault(p.uid, p)
        for lst in self.anchors:
            for p in lst:
                reg.setdefault(p.uid, p)
        nodes = []
        for uid, n in reg.items():
            if n.alive:
                ram = [(int(t[4:]), n.EXP[t]) for t in n.RAM_Index]
                kb = [(i, [p.uid for p in b]) for i, b in n.kbuckets.items()]
            else:
                ram, kb = [], []
            nodes.append((uid, n.node_id, bool(n.alive), ram, kb))
        st = {k: getattr(self, k) for k in (
            'remaining', 'now', 'total_departures', 'repair_msgs', 'n_reanchored', 'n_repairs',
            'exp_pending', 'stage', 'ep_w', 'wsince', 'ep', 'since_repair', 'dep0', 'msg0', 'stats0',
            'hist', 'pre', 'build_info', 'next_uid', 'n_steps')}
        st['timing'] = dict(self.timing)
        blob = {'version': CKPT_VERSION, 'sig': self.cfg['sig'], 'nodes': nodes,
                'slots': [n.uid for n in self.slots],
                'anchors': [[p.uid for p in lst] for lst in self.anchors],
                'state': st, 'stats': dict(STATS), 'n_resumed': self.n_resumed,
                'rng': self.rng.get_state(), 'rng_id': self.rng_id.getstate(),
                'rng_boot': self.rng_boot.getstate(), 'rng_ref': self.rng_ref.get_state(),
                'rng_rep': self.rng_rep.getstate(), 'rnd_route': self.rnd_route.getstate(),
                'py_random': random.getstate(), 'np_random': np.random.get_state()}
        tmp = path + '.tmp'
        with open(tmp, 'wb') as fh:
            pickle.dump(blob, fh, protocol=4)
        os.replace(tmp, path)

    def load(self, blob):
        codes = self.data['codes']
        by_uid = {}
        for uid, node_id, alive, ram, _kb in blob['nodes']:
            n = VEngramNode(None, node_id)
            n.uid = uid
            n.alive = alive
            n.RAM_Index = {self.tags[d]: codes[d] for d, _e in ram}
            n.EXP = {self.tags[d]: e for d, e in ram}
            by_uid[uid] = n
        for uid, _nid, _a, _ram, kb in blob['nodes']:
            by_uid[uid].kbuckets = {i: [by_uid[u] for u in lst] for i, lst in kb}
        self.slots = [by_uid[u] for u in blob['slots']]
        self.anchors = [[by_uid[u] for u in lst] for lst in blob['anchors']]
        for k, v in blob['state'].items():
            if k == 'timing':
                self.timing = collections.Counter(v)
            else:
                setattr(self, k, v)
        STATS.clear()
        STATS.update(blob['stats'])
        self.n_resumed = blob['n_resumed'] + 1
        self.rng.set_state(blob['rng'])
        self.rng_id.setstate(blob['rng_id'])
        self.rng_boot.setstate(blob['rng_boot'])
        self.rng_ref.set_state(blob['rng_ref'])
        self.rng_rep.setstate(blob['rng_rep'])
        self.rnd_route.setstate(blob['rnd_route'])
        random.setstate(blob['py_random'])
        np.random.set_state(blob['np_random'])


def measure_epochs(seed, n_epoch, measure_every, rep, epoch):
    """Đúng các epoch đo của main_churn_engine.main (rải đều, lệch pha ngẫu nhiên trong chu kỳ sửa)."""
    _rs_meas = random.Random(seed + 4242)
    _per_cycle = max(1, int(round(rep / epoch))) if rep > 0 else 1
    eps = set()
    for _k in range(max(6, n_epoch // measure_every)):
        _base = int((_k + 1) * n_epoch / max(6, n_epoch // measure_every))
        _off = _rs_meas.randrange(_per_cycle) if _per_cycle > 1 else 0
        eps.add(min(n_epoch, max(1, _base - _off)))
    eps.add(n_epoch)
    return eps


def make_config(a):
    """Như phần xử lý tham số của main_churn_engine.main."""
    if a.epoch <= 0:
        a.epoch = a.median_session / 12.0
    if a.warmup <= 0:
        a.warmup = a.median_session
    need = max(3 * a.median_session, 3 * a.repair_interval)
    if a.duration < need:
        print(f'[!] Thời lượng {a.duration:.0f}ph quá ngắn, nâng lên {need:.0f}ph')
        a.duration = need
    if a.repair_interval > 0 and a.warmup < 2 * a.repair_interval:
        a.warmup = 2 * a.repair_interval
    n_epoch = max(1, int(round(a.duration / a.epoch)))
    if a.measure_every <= 0:
        a.measure_every = max(1, n_epoch // 6)
    if a.ttl <= 0:
        a.ttl = 2.2 * a.repair_interval if a.repair_interval > 0 else float('inf')
    cfg = dict(vars(a))
    cfg.update({'num_tables': int(os.environ['NUM_TABLES']), 'k_query': K_QUERY,
                'multi_probe': T_PROBE, 'probe_bits': C_BITS, 'pq_variant': a.pq,
                'session_dist': 'weibull', 'repair_mode': 'lazy', 'model': 'iterative',
                'k_bucket': K_BUCKET, 'alpha': ALPHA, 'join': 'đầy đủ (join + làm mới bucket)',
                'maintenance': 'học bên gửi mọi RPC, ping peer cũ nhất khi bucket đầy, xoá contact '
                               'không trả lời, tự tra chính mình mỗi refresh_every phút',
                'n_epoch': n_epoch, 'warmup_epochs': max(1, int(round(a.warmup / a.epoch)))})
    sig = {k: cfg[k] for k in ('dataset', 'nodes', 'seed', 'nq', 'num_files', 'median_session',
                               'weibull_shape', 'duration', 'epoch', 'warmup', 'repair_interval',
                               'ttl', 'meta_anchors', 'measure_every', 'pq', 'refresh_every')}
    sig['commit'] = os.environ.get('RUN_COMMIT', '')
    cfg['sig'] = sig
    return cfg


def load_data(a):
    D = f'./data/{a.dataset}'
    E = np.load(f'{D}_corpus_embeddings.npy')
    n_docs = a.num_files or len(E)
    with open(f'{D}_ground_truth.json', encoding='utf-8') as fh:
        gt = json.load(fh)
    rt.initialize_lsh_projections(a.seed, vector_dim=int(E.shape[1]))
    keys = [rt.generate_multi_semantic_keys(E[i]) for i in range(n_docs)]
    return {'E': E, 'Q': np.load(f'{D}_query_embeddings.npy'),
            'codes': np.load(f'{D}_pq_codes_{a.pq}.npy'),
            'codebook': np.load(f'{D}_pq_codebook_{a.pq}.npy'),
            'gt': gt, 'nq': min(a.nq, len(gt)), 'n_docs': n_docs, 'keys': keys}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', default='code')
    ap.add_argument('--nodes', type=int, default=10000)
    ap.add_argument('--seed', type=int, default=20235956)
    ap.add_argument('--nq', type=int, default=200)
    ap.add_argument('--num-files', type=int, default=0, help='0 = mọi object')
    ap.add_argument('--pq', default='m512')
    ap.add_argument('--meta-anchors', type=int, default=1, metavar='R')
    ap.add_argument('--median-session', type=float, default=120.0, metavar='PHUT')
    ap.add_argument('--weibull-shape', type=float, default=0.5)
    ap.add_argument('--duration', type=float, default=720.0, metavar='PHUT')
    ap.add_argument('--epoch', type=float, default=0, metavar='PHUT', help='0 = median/12')
    ap.add_argument('--warmup', type=float, default=0, metavar='PHUT',
                    help='0 = median, và ít nhất hai chu kỳ sửa')
    ap.add_argument('--repair-interval', type=float, default=0, metavar='PHUT', help='0 = không sửa')
    ap.add_argument('--ttl', type=float, default=0, metavar='PHUT', help='0 = 2,2 chu kỳ sửa')
    ap.add_argument('--measure-every', type=int, default=0)
    ap.add_argument('--refresh-every', type=float, default=60.0, metavar='PHUT',
                    help='chu kỳ tự tra chính mình của mỗi peer (Kademlia: mỗi giờ); 0 = tắt')
    ap.add_argument('--no-pre', action='store_true', help='bỏ lần đo trước warm-up')
    ap.add_argument('--ckpt', default=None, help='file checkpoint (mặc định <out>.ckpt)')
    ap.add_argument('--ckpt-every', type=float, default=float(os.environ.get('CHURN_CKPT_EVERY', '900')),
                    metavar='GIAY', help='chu kỳ ghi checkpoint (mặc định 900, hoặc biến môi trường CHURN_CKPT_EVERY)')
    ap.add_argument('--stop-after', type=float, default=0, metavar='GIAY',
                    help='kiểm thử: ghi checkpoint rồi thoát (mã 75) sau ngần này giây')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    t_start = time.time()
    signal.signal(signal.SIGTERM, lambda _s, _f: STOP.__setitem__('flag', True))
    cfg = make_config(a)
    ckpt = a.ckpt or (a.out + '.ckpt')
    print(f'[*] churn trên mô hình iterative | {a.dataset} | N = {a.nodes} | seed {a.seed} | r = {a.meta_anchors} '
          f'| sửa {"không" if a.repair_interval <= 0 else f"mỗi {a.repair_interval:.0f}ph"} | TTL {cfg["ttl"]} '
          f'| warm-up {a.warmup:.0f}ph ({cfg["warmup_epochs"]} epoch) | đo {a.duration:.0f}ph '
          f'({cfg["n_epoch"]} epoch × {a.epoch:.0f}ph)', flush=True)
    data = load_data(a)
    IT.set_query_rules(IT.DEFAULT_RULES)
    sim = ChurnSim(a, cfg, data)
    blob = None
    if os.path.isfile(ckpt):
        try:
            with open(ckpt, 'rb') as fh:
                blob = pickle.load(fh)
            if blob.get('version') != CKPT_VERSION or blob.get('sig') != cfg['sig']:
                print('[!] checkpoint không khớp cấu hình hoặc commit, chạy lại từ đầu', flush=True)
                blob = None
        except Exception as e:             # checkpoint hỏng: chạy lại từ đầu
            print(f'[!] không đọc được checkpoint ({e}), chạy lại từ đầu', flush=True)
            blob = None
    if blob is not None:
        sim.load(blob)
        print(f'[*] chạy tiếp từ checkpoint: {sim.stage}, warm-up {sim.ep_w}/{sim.n_warm}, '
              f'đo {sim.ep}/{sim.n_epoch} (lần tiếp thứ {sim.n_resumed})', flush=True)
        rt.PHASE_RULES['ingest'] = IT.DEFAULT_RULES
    else:
        t0 = time.time()
        ns = SimpleNamespace(plan='churn', dataset=a.dataset, seed=a.seed, nodes=a.nodes, nq=a.nq,
                             num_files=a.num_files or None, pq=a.pq, join_refresh=1)
        ctx = IT.Ctx(ns)
        IT.join_stage(ctx)
        st = IT.ingest_stage(ctx, 'main', r=a.meta_anchors)
        info = {'join_refresh': ctx.out.get('join_refresh'), 'ingest': st['info'],
                'timing': dict(ctx.out['timing'])}
        sim.build(ctx, info)
        del ctx, st
        sim.timing['build'] += time.time() - t0
        if not a.no_pre:
            t0 = time.time()
            # mạng t = 0: đo ngay sau ingest, trạng thái số ngẫu nhiên như biến thể base của iterative.py
            netmod.iterative_find_k_closest_nodes = _query_lookup
            sim.pre = sim.snapshot(-1, 0.0, phase=None, label='pre')
            sim.timing['snapshots'] += time.time() - t0
        sim.save(ckpt)
    netmod.iterative_find_k_closest_nodes = _query_lookup
    if a.stop_after > 0:
        # kiểm thử chạy tiếp: dừng giữa chừng sau stop_after giây (ở mốc checkpoint kế tiếp)
        _orig = sim.save
        t_stop = time.time() + a.stop_after

        def _save_and_maybe_stop(path):
            _orig(path)
            if time.time() >= t_stop:
                print('[kiểm thử] dừng sau checkpoint', flush=True)
                sys.exit(75)
        sim.save = _save_and_maybe_stop
    sim.run(ckpt, a.ckpt_every)

    sim.timing['total'] = sim.timing.get('build', 0) + sim.timing.get('warmup', 0) + \
        sim.timing.get('main', 0) + sim.timing.get('snapshots', 0)
    out = {'config': {k: v for k, v in cfg.items() if k != 'sig'}, 'corpus': sim.n_docs,
           'history': sim.hist, 'pre': sim.pre,
           'commit': os.environ.get('RUN_COMMIT', ''), 'env': dict(IT.BASE_ENV),
           'build': sim.build_info, 'stats': dict(STATS),
           'n_reanchored': sim.n_reanchored, 'n_repairs': sim.n_repairs,
           'total_departures': sim.total_departures, 'n_resumed': sim.n_resumed,
           'timing': {k: round(v, 1) for k, v in sim.timing.items()},
           'peak_rss_mb': IT.peak_rss_mb()}
    os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
    tmp = a.out + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=1, default=float)
    os.replace(tmp, a.out)
    if os.path.isfile(ckpt):
        os.remove(ckpt)
    h = sim.hist
    print(f'-> Lưu: {a.out} | R@5 cuối {h[-1]["final_r5"]:.1f} | min phys {min(x["meta_physical"] for x in h[1:] or h):.1f} '
          f'| {time.time() - t_start:.0f} giây lần này | RSS đỉnh {out["peak_rss_mb"]:.0f} MB', flush=True)


if __name__ == '__main__':
    main()
