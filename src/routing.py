import numpy as np
import hashlib
import hmac

# ============================================================================
# CẤU HÌNH LSH ĐA VŨ TRỤ (MULTI-INDEX)
# ============================================================================
VECTOR_DIM = 1024
import os as _os
NUM_PROJECTIONS = int(_os.environ.get("NUM_TABLES", "5"))   # L — bảng chiếu độc lập
DEFAULT_LSH_SEED = 20235956

# --- Tham số giao thức, khớp Table 2 trong paper ---
DEFAULT_ALPHA = 3        # alpha — độ song song của lookup
# Điều kiện dừng của Ripple Search: "exhaust" = Kademlia chuẩn (đúng),
# "unchanged" = hành vi cũ, giữ để đo chênh lệch.
# Mặc định "unchanged" — KHÔNG phải vì nó đúng theo Kademlia, mà vì đo được
# nó tốt hơn cho tác vụ này ở MỌI mặt: recall cao hơn 5,1 điểm, RPC ít hơn 31%,
# và phủ nhiều node phân biệt hơn. Quét R_max = 15/30/60 cho thấy trần không
# phải nguyên nhân — cả hai điều kiện cho kết quả y hệt ở cả ba mức.
#
# Lý do: Kademlia chuẩn hội tụ về k node GẦN NHẤT, đúng cho tra khoá chính xác.
# Truy vấn tương tự cần PHỦ VÙNG. Điều kiện "unchanged" tiếp tục thăm dò ra
# ngoài top-k khi top-k đã hỏi hết, nên gom được tập ứng viên rộng hơn.
# HAI TRỤC ĐỘC LẬP, trước đây bị trộn làm một.
#
# STOP_RULE — khi nào dừng:
#   "stable"  : frontier K-peer không đổi qua hai vòng liên tiếp.
#               Đây là frontier-stability termination. KHÔNG chứng minh vùng đã
#               được liệt kê; nó chấp nhận frontier xấp xỉ thay vì tiêu thêm RPC
#               để hội tụ về các peer XOR-gần hơn trên toàn cục.
#   "exhaust" : mọi node trong top-K hiện tại đã được hỏi.
#               Đây là exhaustive top-K frontier termination.
#
# FRONTIER_SCOPE — hỏi node nào:
#   "all"  : node gần nhất chưa hỏi trong TOÀN BỘ tập ứng viên đã phát hiện.
#            Khi top-K đã hỏi hết, tiếp tục ra ngoài frontier.
#   "topk" : chỉ node nằm trong top-K hiện tại.
#
# Mặc định ("stable", "all") là hành vi đã đo. Tách hai trục để biết lợi thế
# đến từ điều kiện dừng hay từ phạm vi hỏi — hai thứ đòi hai cách mô tả khác
# nhau trong bài.
STOP_RULE      = _os.environ.get("STOP_RULE", "stable")
# Ablation multi-probe: "margin" lật bit |projection| nhỏ nhất (mặc định),
# "random" lật bit ngẫu nhiên — để kiểm heuristic margin có tác dụng thật không.
PROBE_ORDER = _os.environ.get("PROBE_ORDER", "margin")
# L2-normalize từng cột ma trận chiếu để margin so sánh được giữa các bit.
NORMALIZE_ROWS = _os.environ.get("NORMALIZE_ROWS", "1") == "1"
# Chẩn đoán (đắt): đo trùng khớp với tập K peer XOR-gần nhất toàn cục.
FRONTIER_SCOPE = _os.environ.get("FRONTIER_SCOPE", "all")

# Chẩn đoán: đo tập trả về trùng bao nhiêu với tập K peer XOR-gần nhất toàn cục.
MEASURE_OVERLAP = _os.environ.get("MEASURE_OVERLAP", "0") == "1"
_ALL_NODES = []          # do main_simulation.py gán sau khi dựng mạng
_OVERLAP_STATS = []
import os as _os
# Mục 21: quét R_max qua biến môi trường
DEFAULT_R_MAX = int(_os.environ.get("R_MAX", "15"))   # trần số vòng mỗi lookup

# ---------------------------------------------------------------------------
# QUY TẮC DỪNG THEO PHA (ppna-r1, mục 2.3 của tài liệu sửa bài)
#
# STOP_RULE / FRONTIER_SCOPE / R_MAX áp cho CẢ tiến trình, nên mỗi biến thể
# của bảng termination đổi luôn ba thứ: bảng định tuyến dựng lúc join, vị trí
# record lúc ingest, và lookup lúc truy vấn. Các biến dưới đây cho phép cố định
# join và ingest trong khi chỉ đổi quy tắc truy vấn:
#     JOIN_STOP_RULE   JOIN_FRONTIER_SCOPE   JOIN_R_MAX
#     INGEST_STOP_RULE INGEST_FRONTIER_SCOPE INGEST_R_MAX
# Không đặt thì pha đó dùng STOP_RULE / FRONTIER_SCOPE / R_MAX như cũ, nên mọi
# kết quả cũ giữ nguyên từng bit. Pha truy vấn, payload và mọi lời gọi không
# ghi pha luôn dùng STOP_RULE / FRONTIER_SCOPE / R_MAX.
# ---------------------------------------------------------------------------
def _phase_env(prefix):
    sr = _os.environ.get(f"{prefix}_STOP_RULE")
    fs = _os.environ.get(f"{prefix}_FRONTIER_SCOPE")
    if sr is not None and sr not in ("stable", "exhaust"):
        raise SystemExit(f"{prefix}_STOP_RULE phải là stable hoặc exhaust, nhận '{sr}'")
    if fs is not None and fs not in ("all", "topk"):
        raise SystemExit(f"{prefix}_FRONTIER_SCOPE phải là all hoặc topk, nhận '{fs}'")
    return (STOP_RULE if sr is None else sr,
            FRONTIER_SCOPE if fs is None else fs,
            int(_os.environ.get(f"{prefix}_R_MAX", str(DEFAULT_R_MAX))))


PHASE_RULES = {
    None: (STOP_RULE, FRONTIER_SCOPE, DEFAULT_R_MAX),
    "join": _phase_env("JOIN"),
    "ingest": _phase_env("INGEST"),
}


def phase_rules(phase=None):
    """(stop_rule, frontier_scope, r_max) của một pha; pha khác join/ingest dùng quy tắc truy vấn."""
    return PHASE_RULES.get(phase, PHASE_RULES[None])


def rules_summary():
    """Chuỗi mô tả quy tắc từng pha, để ghi vào JSON kết quả."""
    return {ph or "query": "%s/%s/R%d" % phase_rules(ph) for ph in (None, "join", "ingest")}


# Thống kê lookup theo pha: số lookup, tổng vòng, tổng RPC, và lý do dừng
# ("cap" = chạy hết R_max, "stable" = frontier ổn định, "empty" = hết peer để hỏi).
# Chỉ đếm, không dùng số ngẫu nhiên nên không đổi kết quả.
LOOKUP_STATS = {}


def _note_lookup(phase, hops, rpcs, reason):
    s = LOOKUP_STATS.get(phase or "other")
    if s is None:
        s = LOOKUP_STATS[phase or "other"] = {"n": 0, "hops": 0, "rpcs": 0,
                                              "cap": 0, "stable": 0, "empty": 0}
    s["n"] += 1
    s["hops"] += hops
    s["rpcs"] += rpcs
    s[reason] += 1


def lookup_stats_summary():
    out = {}
    for ph, s in LOOKUP_STATS.items():
        n = max(s["n"], 1)
        out[ph] = {"n": s["n"], "mean_rounds": s["hops"] / n, "mean_rpcs": s["rpcs"] / n,
                   "frac_cap": s["cap"] / n, "frac_stable": s["stable"] / n,
                   "frac_empty": s["empty"] / n}
    return out


# MEASURE_OVERLAP=1 bật hai phép đo đắt: thứ hạng XOR của peer trả về trong
# từng probe truy vấn (xor_rank_mean), và độ trùng với tập XOR-gần nhất cho MỌI
# lookup sau khi dựng mạng (overlap_mean, gồm cả 100.000 lookup lúc ingest).
# OVERLAP_STATS=0 tắt riêng phép đo thứ hai để chạy nhanh hơn; xor_rank_mean
# giữ nguyên. Không ảnh hưởng kết quả định tuyến.
OVERLAP_STATS = _os.environ.get("OVERLAP_STATS", "1") == "1"
DEFAULT_MULTI_PROBE = 3  # T — số prefix probe mỗi bảng (mục 3.5)
DEFAULT_PROBE_BITS = 16  # c — số bit đầu được phép lật khi probe

# Khai báo rỗng, KHÔNG sinh ma trận ngay lúc import file
PROJECTION_MATRICES = []

# ppna-r1 đợt 1 (R1-1, R1-6):
# PROJ_FAMILY: "achlioptas" (mặc định, như bài) hoặc "gaussian" (SRP đẳng hướng),
#   cả hai cùng chuẩn hoá cột. Gaussian dùng dòng số riêng của chính nó.
# Mọi số bảng L đều sinh từ CÙNG một dòng số ngẫu nhiên, nên L bảng đầu của cấu
# hình L lớn trùng đúng L bảng của cấu hình nhỏ hơn. Với L <= 5 ma trận giữ
# nguyên từng bit như trước.
# Cột Achlioptas toàn 0 (xác suất (2/3)^d mỗi cột) được sinh lại như Mục 3.1
# viết, bằng dòng số riêng của cột đó, nên dòng số chính không đổi khi trường
# hợp này không xảy ra.
PROJ_FAMILY = _os.environ.get("PROJ_FAMILY", "achlioptas")
ZERO_COLUMNS_REDRAWN = 0


def _redraw_zero_columns(matrix, seed, table_idx):
    zero = np.flatnonzero(~matrix.any(axis=0))
    for j in zero:
        rs = np.random.RandomState((int(seed) * 1000003 + table_idx * 1009 + int(j)) % (2 ** 32))
        col = np.zeros(matrix.shape[0], dtype=np.float32)
        while not col.any():
            col = rs.choice([0, 1, -1], size=matrix.shape[0], p=[2/3, 1/6, 1/6]).astype(np.float32)
        matrix[:, j] = col
    return len(zero)


def generate_lsh_projections(seed, vector_dim=VECTOR_DIM, num_projections=None, family=None):
    """Sinh ma trận chiếu bằng Local Random Generator, miễn nhiễm với bên ngoài"""
    global ZERO_COLUMNS_REDRAWN
    if num_projections is None:
        num_projections = NUM_PROJECTIONS
    family = family or PROJ_FAMILY
    if family not in ("achlioptas", "gaussian"):
        raise SystemExit(f"PROJ_FAMILY phải là achlioptas hoặc gaussian, nhận '{family}'")
    rng = np.random.RandomState(seed)
    projections = []
    for t in range(num_projections):
        if family == "gaussian":
            matrix = rng.standard_normal((vector_dim, 160)).astype(np.float32)
        else:
            # Achlioptas Distribution: P(1)=1/6, P(-1)=1/6, P(0)=2/3
            matrix = rng.choice([0, 1, -1], size=(vector_dim, 160),
                                p=[2/3, 1/6, 1/6]).astype(np.float32)
            ZERO_COLUMNS_REDRAWN += _redraw_zero_columns(matrix, seed, t)
        if NORMALIZE_ROWS:
            # L2-normalize TỪNG CỘT (mỗi cột là một hyperplane, một bit sketch).
            # Không normalize thì |projection| của hai bit có số nonzero khác
            # nhau không so được, mà margin-ranked probing xếp hạng đúng theo
            # đại lượng đó. Đây là lỗi ảnh hưởng trực tiếp mục 2.1 của thầy.
            nrm = np.linalg.norm(matrix, axis=0, keepdims=True)
            nrm[nrm == 0] = 1.0
            matrix = matrix / nrm
        projections.append(matrix)
    return projections

def initialize_lsh_projections(seed=DEFAULT_LSH_SEED, vector_dim=VECTOR_DIM,
                               num_projections=None, family=None):
    """Hàm này sẽ được gọi ở main.py mỗi khi bắt đầu một Seed mới"""
    global PROJECTION_MATRICES
    PROJECTION_MATRICES = generate_lsh_projections(seed, vector_dim, num_projections, family)

def generate_multi_semantic_keys(vector):
    """
    Sinh ra 3 Semantic Keys 160-bit khác nhau cho cùng một Vector.
    Mỗi Key đại diện cho một 'góc nhìn' ngữ nghĩa khác nhau.
    """
    # Rào bảo vệ: Đề phòng quên chưa gọi initialize()
    if not PROJECTION_MATRICES:
        initialize_lsh_projections()
        
    vec = np.asarray(vector).flatten()
    keys = []
    for i in range(len(PROJECTION_MATRICES)):
        # Nhân ma trận thưa và lấy dấu (Sign)
        bits = (np.dot(vec, PROJECTION_MATRICES[i]) > 0).astype(int)
        bit_string = "".join(map(str, bits))
        keys.append(int(bit_string, 2))
    return keys

def generate_semantic_key(vector):
    """Hàm wrapper cho các logic cũ cần 1 key (mặc định lấy key đầu tiên)"""
    return generate_multi_semantic_keys(vector)[0]


def generate_probe_keys(vector, table_idx, T=DEFAULT_MULTI_PROBE, c=DEFAULT_PROBE_BITS):
    """Multi-probe prefix selection (paper mục 3.5).

    Sinh T prefix cho MỘT bảng chiếu: key gốc + (T-1) biến thể lật bit YẾU nhất.

    Bit i ghi dấu của (v . r_i). Độ lớn |v . r_i| cho biết vector nằm xa hay gần
    siêu phẳng chiếu:
      - |proj| LỚN  -> bit ổn định, neighbor gần góc gần như chắc chắn đồng ý
      - |proj| NHỎ  -> vector sát siêu phẳng, đây CHÍNH LÀ bit mà neighbor dễ
                       bất đồng (boundary effect, mục 3.2)
    Nên xếp c bit đầu theo |proj| tăng dần = xếp theo xác suất neighbor lệch ở đó.
    Lật những bit yếu nhất = nhảy sang subtree mà neighbor nhiều khả năng rơi vào.

    Khác với việc tăng K (mở rộng frontier quanh CÙNG một prefix): probe đi tới
    các subtree KHÁC NHAU mà frontier mở rộng không bao giờ chạm tới.
    """
    if not PROJECTION_MATRICES:
        initialize_lsh_projections()

    vec = np.asarray(vector).flatten()
    proj = np.dot(vec, PROJECTION_MATRICES[table_idx])
    bits = (proj > 0).astype(int)
    base = int("".join(map(str, bits)), 2)

    keys = [base]
    if T <= 1:
        return keys

    c = min(c, 160)
    if PROBE_ORDER == "random":
        _rs = np.random.RandomState(int(abs(proj[:c].sum() * 1e6)) % (2**31))
        weak_first = _rs.permutation(c)        # ABLATION: lật bit ngẫu nhiên
    else:
        weak_first = np.argsort(np.abs(proj[:c]))   # bit yếu nhất trước
    for j in weak_first[: T - 1]:
        keys.append(base ^ (1 << (159 - int(j))))   # lật bit j (bit 0 = MSB)
    return keys

USER_SECRET_KEY = b"v_engram_dummy_secret_key"

def generate_placement_key(object_tag, shard_id):
    """Placement key độc lập ngữ nghĩa: K_place(s) = HMAC(tag, s) trên toàn bộ
    không gian khoá 160-bit của Kademlia.

    Không phụ thuộc semantic key, nên các shard được rải ĐỀU khắp không gian địa chỉ
    và mọi vị trí đều tái tạo được CHỈ từ object_tag (phục vụ khôi phục stateless).
    Đây là tầng PAYLOAD: mỗi object chỉ đặt MỘT bộ 30 shard (không nhân theo L).
    """
    seed_str = f"{object_tag}_shard_{shard_id}".encode("utf-8")
    mac_hash = hmac.new(USER_SECRET_KEY, seed_str, hashlib.sha256).hexdigest()
    # SHA-256 cho 256 bit -> thu về 160-bit keyspace
    return int(mac_hash, 16) % (1 << 160)

def iterative_find_k_closest_nodes(key, bootstrap_node, alpha=DEFAULT_ALPHA,
                                   k=20, max_rounds=None, phase=None):
    """Ripple Search cho MỘT prefix (paper Algorithm 1).

    Đây là thủ tục KHÁM PHÁ LÂN CẬN theo lối best-first có ngân sách, chạy trên
    trạng thái định tuyến Kademlia — KHÔNG phải một lookup Kademlia chính xác.
    Mục tiêu là gom một tập peer hữu ích quanh điểm hẹn ngữ nghĩa dưới một ngân
    sách định tuyến, không phải hội tụ về K peer XOR-gần nhất trên toàn cục.

    HAI TRỤC ĐỘC LẬP: STOP_RULE và FRONTIER_SCOPE (xem chú thích ở đầu file).

    Cả hai đều bị chặn bởi R_max.
    KHÔNG dùng tiêu chí "XOR distance nhỏ nhất chững lại" — tiêu chí đó dừng
    ngay khi frontier vừa tới đích, trước khi kịp gom hàng xóm (mục 3.4).

    Trả về (k node gần nhất, số vòng, số RPC).
    Ba đại lượng rounds/RPC/contacted-nodes được đếm TÁCH BẠCH (mục 3.9).

    phase ("join", "ingest", "query", "payload" hoặc None) chọn quy tắc dừng
    theo PHASE_RULES và là nhãn cho LOOKUP_STATS. max_rounds=None lấy R_max
    của pha đó.
    """
    stop_rule, frontier_scope, phase_rmax = phase_rules(phase)
    if max_rounds is None:
        max_rounds = phase_rmax
    candidates = set([bootstrap_node])
    candidates.update(bootstrap_node.get_neighbors())
    queried = set()
    prev_best = None
    hops = 0
    rpcs = 0
    reason = "cap"

    for _ in range(max_rounds):
        ordered = sorted(candidates, key=lambda node: node.node_id ^ key)

        pool = ordered if frontier_scope == "all" else ordered[:k]
        to_query = [node for node in pool if node not in queried][:alpha]

        if not to_query:
            reason = "empty"
            break          # với scope="topk" đây chính là exhaustive termination

        hops += 1
        for node in to_query:
            queried.add(node)
            rpcs += 1                      # mỗi FIND_NODE là một RPC
            # Kademlia trả về k contact GẦN NHẤT với khoá, không phải toàn
            # bộ bảng. Nhánh ring giữ hành vi cũ để đối chiếu.
            if hasattr(node, "kb_closest") and node.kbuckets:
                candidates.update(node.kb_closest(key, k))
            else:
                candidates.update(node.get_neighbors())

        if stop_rule == "stable":
            best_ids = tuple(node.node_id for node in ordered[:k])
            if best_ids == prev_best:
                reason = "stable"
                break
            prev_best = best_ids

    ordered = sorted(candidates, key=lambda node: node.node_id ^ key)
    result = ordered[:k]

    # ĐO ĐỘ LỆCH SO VỚI TẬP XOR-GẦN NHẤT TOÀN CỤC.
    #
    # Đây là bằng chứng trực tiếp cho luận điểm rằng Ripple Search KHÔNG nhắm
    # hội tụ về K peer gần nhất: nếu tập trả về lệch nhiều so với tập gần nhất
    # toàn cục mà recall lại CAO hơn, thì rõ ràng hội tụ XOR không phải mục tiêu.
    #
    # Đắt (sắp xếp toàn mạng mỗi lookup) nên chỉ bật khi chẩn đoán.
    if MEASURE_OVERLAP and OVERLAP_STATS and _ALL_NODES:
        true_k = sorted(_ALL_NODES, key=lambda nd: nd.node_id ^ key)[:k]
        ov = len({nd.node_id for nd in result} & {nd.node_id for nd in true_k})
        _OVERLAP_STATS.append(ov / max(k, 1))

    _note_lookup(phase, hops, rpcs, reason)
    return result, hops, rpcs