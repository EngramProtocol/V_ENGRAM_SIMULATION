import simpy
import random
from src.network import (
    bootstrap_network,
    refresh_buckets,
    data_ingestion_process,
    PLACEMENT_CANDIDATES,
    METADATA_ANCHORS,
    K_QUERY,
)
from src.routing import (
    generate_placement_key,
    generate_multi_semantic_keys,
    iterative_find_k_closest_nodes,
)
import numpy as np

import os as _os
# Tham số hoá qua biến môi trường để script chạy nhiều cấu hình:
#   DATASET=scifact NUM_FILES=5183 python3 main_churn_test.py
DATASET = _os.environ.get("DATASET", "code")          # code | scifact | squad
EMBEDDINGS_PATH = f"./data/{DATASET}_corpus_embeddings.npy"
# PQ code chỉ được lưu, không ảnh hưởng availability. Mặc định giữ file cũ
# (không hậu tố, m=256); PQ_VARIANT=m512 dùng file của bài.
PQ_VARIANT = _os.environ.get("PQ_VARIANT", "")
_PQSFX = f"_{PQ_VARIANT}" if PQ_VARIANT and PQ_VARIANT != "m256" else ""
PQ_CODES_PATH = f"./data/{DATASET}_pq_codes{_PQSFX}.npy"

# ---- ppna-r1 (mục 2.4 của tài liệu sửa bài) ----
# NET_SEED: đặt seed cho ID peer, cấu trúc overlay và ma trận chiếu trước khi
#   dựng mạng. Bản cũ KHÔNG đặt seed nên mỗi lần chạy là một mạng khác và không
#   tái lập được. Không đặt thì giữ hành vi cũ.
# INGEST_SAMPLE_ONLY=1: chỉ ingest RECOVERY_SAMPLE object sẽ được đo. Mọi đại
#   lượng đo chỉ phụ thuộc anchor và shard của chính object đó, nên kết quả
#   tương đương về phân phối mà nhanh hơn ~NUM_FILES/RECOVERY_SAMPLE lần.
#   Danh sách object giống hệt bản cũ (cùng SAMPLE_SEED).
# OUT_JSON: ghi bảng kết quả ra file JSON ngoài phần in ra màn hình.
NET_SEED = _os.environ.get("NET_SEED")
INGEST_SAMPLE_ONLY = _os.environ.get("INGEST_SAMPLE_ONLY", "0") == "1"
OUT_JSON = _os.environ.get("OUT_JSON")
# ---- ppna-r1 đợt 6 (Bảng 9 với join đầy đủ) ----
# JOIN_REFRESH=n: sau bootstrap_network, chạy n vòng làm mới k-bucket (refresh_buckets) như
#   join của Kademlia gốc, cùng bộ sinh số với ppna_r1/dot2/iterative.py (--join-refresh).
#   Vòng làm mới không đụng random của Python. Mặc định 0: join cũ, hành vi như trước.
# RECORD_KILLS=1: ghi ID các peer bị tắt ở từng mức mất vào OUT_JSON (killed_hex). Không
#   dùng thêm số ngẫu nhiên nào, nên mọi số đo trùng lần chạy không ghi.
# KILL_FROM=<json>: tắt đúng các peer đã ghi trong file đó (cùng NET_SEED, cùng CHURN_STEPS)
#   thay vì rút ngẫu nhiên, để hai cách dựng mạng được so trên cùng tập peer chết.
# REFRESH_CACHE=<file>: bảng định tuyến sau vòng làm mới không phụ thuộc r (r chỉ dùng lúc ingest),
#   nên job đầu tiên của một seed ghi k-bucket đã làm mới vào file này và các job sau của cùng seed
#   nạp lại thay vì làm mới lần nữa. Chỉ nạp khi file khớp commit (RUN_COMMIT), NET_SEED, số vòng,
#   tập peer và bảng định tuyến trước khi làm mới; khác bất kỳ điều nào thì làm mới như thường và ghi
#   đè. Việc nạp không dùng số ngẫu nhiên nào; nhóm chk và smoke của ppna_r1/dot6 kiểm kết quả trùng
#   từng số với lần làm mới thật.
JOIN_REFRESH = int(_os.environ.get("JOIN_REFRESH", "0"))
REFRESH_CACHE = _os.environ.get("REFRESH_CACHE")
RECORD_KILLS = _os.environ.get("RECORD_KILLS", "0") == "1"
KILL_FROM = _os.environ.get("KILL_FROM")

NUM_NODES = int(_os.environ.get("NUM_NODES", "10000"))
NUM_FILES = int(_os.environ.get("NUM_FILES", "20000"))  # code=20000, scifact=5183
SHARDS_PER_FILE = 30
K_SIZE = 20
K_REQUIRED = 20
RECOVERY_SAMPLE = int(_os.environ.get("RECOVERY_SAMPLE", "500"))
CHURN_STEPS = [float(x) for x in
               _os.environ.get("CHURN_STEPS", "0,0.10,0.20,0.30").split(",")]
SAMPLE_SEED = int(_os.environ.get("SAMPLE_SEED", "2026"))


def kill_random_nodes(network_nodes, target_ratio, total_nodes, forced_ids=None):
    """Tắt peer cho tới khi còn (1 - target_ratio) * total_nodes peer. Trả về tập peer bị tắt
    ở bước này. forced_ids (đợt 6): tắt đúng các peer có ID này thay vì rút ngẫu nhiên."""
    desired_remaining = int(total_nodes * (1 - target_ratio))
    kill_count = max(0, len(network_nodes) - desired_remaining)
    if forced_ids is not None:
        want = set(forced_ids)
        killed = {node for node in network_nodes if node.node_id in want}
        if len(killed) != len(want) or len(killed) != kill_count:
            raise SystemExit(f"KILL_FROM: cần tắt {kill_count} peer, file ghi {len(want)}, "
                             f"tìm thấy {len(killed)} trong mạng")
    elif kill_count == 0:
        return set()
    else:
        killed = set(random.sample(network_nodes, min(kill_count, len(network_nodes))))
    if not killed:
        return killed
    network_nodes[:] = [node for node in network_nodes if node not in killed]
    for node in network_nodes:
        node.routing_table.difference_update(killed)
        # Ở overlay k-bucket, lookup đọc kbuckets chứ không đọc routing_table.
        # Không gỡ thì peer chết vẫn được hỏi, vẫn trả contact và vẫn "giữ"
        # metadata. Gỡ ngay là cùng ngữ nghĩa với nhánh ring ở trên. Overlay ring
        # không có kbuckets nên dòng này không đổi gì ở đó.
        if node.kbuckets:
            for _i, _b in node.kbuckets.items():
                node.kbuckets[_i] = [p for p in _b if p not in killed]
    return killed


def metadata_alive(vector, tag, network_nodes):
    """Metadata của object còn tìm được không, sau khi node chết?

    Bản cũ tra GLOBAL_METADATA_DHT (dict toàn cục) => metadata KHÔNG BAO GIỜ chết,
    nên thí nghiệm chỉ đo ngưỡng erasure code chứ không đo discovery. Nay client
    phải ĐỊNH TUYẾN THẬT tới các anchor còn sống, đúng như lúc query.

    Với r nhỏ (r=1 => 5 anchor/object trên toàn mạng), đây là phép đo có ý nghĩa:
    mất hết anchor là mất khả năng tìm thấy object dù payload còn nguyên.
    """
    if not network_nodes:
        return False
    for s_key in generate_multi_semantic_keys(vector):
        bootstrap_node = random.choice(network_nodes)
        anchors, _, _ = iterative_find_k_closest_nodes(
            s_key, bootstrap_node, alpha=3, k=K_QUERY
        )
        for node in anchors:
            if tag in node.RAM_Index:
                return True          # còn ít nhất 1 anchor sống ở bảng này
    return False


def can_recover_payload(tag, network_nodes):
    """Payload đặt 1 lần: tái tạo 30 placement key CHỈ từ tag, cần >=20/30 shard sống sót.

    Trả về (giải mã được, số shard lookup tìm thấy). Vòng lặp dừng sớm khi đủ 20
    shard như bản cũ, nên dòng số ngẫu nhiên và kết quả giữ nguyên từng bit.
    """
    shards_collected = 0
    for s_id in range(SHARDS_PER_FILE):
        if not network_nodes:
            break
        p_key = generate_placement_key(tag, s_id)
        bootstrap_node = random.choice(network_nodes)
        candidate_nodes, _, _ = iterative_find_k_closest_nodes(
            p_key, bootstrap_node, alpha=3, k=PLACEMENT_CANDIDATES
        )
        for target_node in candidate_nodes:
            if f"{tag}_shard_{s_id}" in target_node.SSD_Storage:
                shards_collected += 1
                break
        if shards_collected >= K_REQUIRED:
            break

    return shards_collected >= K_REQUIRED, shards_collected


def build_holder_index(network_nodes, doc_ids):
    """ppna-r1 đợt 1: peer nào giữ shard và discovery record của các object được đo.

    Dựng một lần sau ingest, chỉ đọc bộ nhớ của peer, không dùng số ngẫu nhiên.
    Dùng để tách hai nguyên nhân mất: shard (hay anchor) đã chết cùng peer, và
    shard còn sống nhưng lookup không tìm thấy.
    """
    tags = {f"doc_{d}" for d in doc_ids}
    shard_holders, meta_holders = {}, {}
    for node in network_nodes:
        for lab in node.SSD_Storage:
            if lab.split("_shard_")[0] in tags:
                shard_holders.setdefault(lab, []).append(node)
        for tag in node.RAM_Index:
            if tag in tags:
                meta_holders.setdefault(tag, []).append(node)
    return shard_holders, meta_holders


def count_recovered_files(network_nodes, doc_ids, vectors, holders=None):
    """Đo TÁCH BẠCH 3 tầng, vì chúng hỏng vì lý do khác nhau:
      - metadata availability: routing còn tìm được discovery record không (phụ thuộc r)
      - payload decode      : còn >=20/30 shard không (phụ thuộc erasure code)
      - end-to-end          : cần CẢ HAI
    Bản cũ gộp tất cả và bỏ qua tầng metadata, nên chỉ đo được erasure code.
    """
    meta_ok = payload_ok = e2e_ok = 0
    phys = {"meta_phys": 0, "payload_phys": 0, "lookup_miss": 0, "alive_sum": 0,
            "found_failed_sum": 0, "alive_failed_sum": 0, "n_failed": 0}
    live = set(network_nodes)
    for doc_id in doc_ids:
        tag = f"doc_{doc_id}"
        m = metadata_alive(vectors[doc_id], tag, network_nodes)
        p, found = can_recover_payload(tag, network_nodes)
        meta_ok += m
        payload_ok += p
        e2e_ok += (m and p)
        if holders is not None:
            shard_holders, meta_holders = holders
            n_alive = sum(1 for s_id in range(SHARDS_PER_FILE)
                          if any(h in live for h in shard_holders.get(f"{tag}_shard_{s_id}", ())))
            phys["meta_phys"] += any(h in live for h in meta_holders.get(tag, ()))
            phys["payload_phys"] += n_alive >= K_REQUIRED
            phys["lookup_miss"] += (n_alive >= K_REQUIRED) and not p
            phys["alive_sum"] += n_alive
            if not p:
                phys["n_failed"] += 1
                phys["found_failed_sum"] += found
                phys["alive_failed_sum"] += n_alive
    return meta_ok, payload_ok, e2e_ok, phys


def run_churn_test(env):
    import src.network as _netmod
    _bs = f" BOOTSTRAP={_netmod.BOOTSTRAP}" if _netmod.ROUTING_TABLE == "kbucket" else ""
    print(f"[*] ROUTING_TABLE={_netmod.ROUTING_TABLE}{_bs} "
          f"NET_SEED={NET_SEED} SAMPLE_SEED={SAMPLE_SEED} "
          f"INGEST_SAMPLE_ONLY={int(INGEST_SAMPLE_ONLY)} r={METADATA_ANCHORS}")
    print("[*] Khoi tao mang P2P...")
    network_nodes = yield env.process(bootstrap_network(env, NUM_NODES, K_SIZE))
    _contacts = [len(n.routing_table) for n in network_nodes]
    _refresh = []
    if JOIN_REFRESH > 0:
        if NET_SEED is None:
            raise SystemExit("JOIN_REFRESH cần NET_SEED")
        import gzip, hashlib, pickle
        _pos = {n.node_id: i for i, n in enumerate(network_nodes)}

        def _kb_pos():
            return [[(_b, [_pos[p.node_id] for p in _lst]) for _b, _lst in n.kbuckets.items()]
                    for n in network_nodes]

        _key = {"commit": _os.environ.get("RUN_COMMIT", ""), "net_seed": NET_SEED, "rounds": JOIN_REFRESH,
                "ids_hash": hashlib.sha1("".join(f"{n.node_id:040x}" for n in network_nodes)
                                         .encode()).hexdigest(),
                "pre_hash": hashlib.sha1(repr(_kb_pos()).encode()).hexdigest()}
        _cache = None
        if REFRESH_CACHE and _os.path.exists(REFRESH_CACHE):
            with gzip.open(REFRESH_CACHE, "rb") as _fh:
                _cache = pickle.load(_fh)
            if any(_cache.get(k) != v for k, v in _key.items()):
                print(f"[!] REFRESH_CACHE {REFRESH_CACHE} không khớp lần chạy này, làm mới lại")
                _cache = None
        _refresh_loaded = _cache is not None
        if _cache is not None:
            for _node, _bk in zip(network_nodes, _cache["kbuckets"]):
                _node.kbuckets.clear()
                _node.kbuckets.update({_b: [network_nodes[_j] for _j in _lst] for _b, _lst in _bk})
                _node.routing_table = set(p for b in _node.kbuckets.values() for p in b)
            _refresh = _cache["info"]
            print(f"[*] Join đầy đủ: nạp k-bucket đã làm mới từ {REFRESH_CACHE}")
        else:
            _rng = np.random.RandomState((int(NET_SEED) * 104729 + 7) % (2 ** 32))
            for _rnd in range(1, JOIN_REFRESH + 1):
                _info = refresh_buckets(network_nodes, _rng)
                _refresh.append(_info)
                print(f"[*] Join đầy đủ, làm mới {_rnd}: {_info['lookups']} lookup, contact TB "
                      f"{_info['contacts_mean']:.1f} (min {_info['contacts_min']})")
            if REFRESH_CACHE:
                _os.makedirs(_os.path.dirname(REFRESH_CACHE) or ".", exist_ok=True)
                _tmp = f"{REFRESH_CACHE}.{_os.getpid()}.tmp"
                with gzip.open(_tmp, "wb") as _fh:
                    pickle.dump(dict(_key, info=_refresh, kbuckets=_kb_pos()), _fh, protocol=4)
                _os.replace(_tmp, REFRESH_CACHE)
        _contacts = [len(n.routing_table) for n in network_nodes]
    _forced = None
    if KILL_FROM:
        import json as _json
        with open(KILL_FROM, encoding="utf-8") as _fh:
            _kf = _json.load(_fh)
        if _kf.get("net_seed") != NET_SEED or [float(x) for x in _kf["churn_steps"]] != CHURN_STEPS:
            raise SystemExit("KILL_FROM: khác NET_SEED hoặc CHURN_STEPS")
        _forced = [[int(h, 16) for h in step] for step in _kf["killed_hex"]]

    # Cùng danh sách với bản cũ: random.Random(s).sample == random.seed(s); random.sample
    _pre = None
    if INGEST_SAMPLE_ONLY:
        _pre = random.Random(SAMPLE_SEED).sample(range(NUM_FILES),
                                                 min(RECOVERY_SAMPLE, NUM_FILES))
    print("[*] Dang phan bo du lieu...")
    yield env.process(data_ingestion_process(
        env, network_nodes, NUM_FILES, SHARDS_PER_FILE,
        embeddings_path=EMBEDDINGS_PATH, pq_codes_path=PQ_CODES_PATH,
        data_label=DATASET.upper(), doc_ids=_pre))

    vectors = np.load(EMBEDDINGS_PATH)

    random.seed(SAMPLE_SEED)
    doc_ids = random.sample(range(NUM_FILES), min(RECOVERY_SAMPLE, NUM_FILES))
    if _pre is not None and _pre != doc_ids:
        raise SystemExit("INGEST_SAMPLE_ONLY: danh sách object lệch với bản cũ")

    print("\n" + "=" * 70)
    print(f"THI NGHIEM: NODE FAILURE TINH (r={METADATA_ANCHORS}, {len(doc_ids)} object mau)")
    print("LUU Y: day KHONG phai churn. Node bi tat truoc khi query va khong quay lai;")
    print("       khong co bucket refresh, khong re-anchor, khong shard repair.")
    print("=" * 70)
    print(f"{'Node loss':>10s} {'Metadata':>12s} {'Payload':>12s} {'End-to-end':>12s}")

    total_nodes = len(network_nodes)
    n = len(doc_ids)
    holders = build_holder_index(network_nodes, doc_ids)
    rows = []
    killed_hex = []
    for _step, churn_ratio in enumerate(CHURN_STEPS):
        _killed = kill_random_nodes(network_nodes, churn_ratio, total_nodes,
                                    forced_ids=None if _forced is None else _forced[_step])
        if RECORD_KILLS:
            killed_hex.append(sorted(f"{x.node_id:040x}" for x in _killed))
        meta_ok, payload_ok, e2e_ok, ph = count_recovered_files(network_nodes, doc_ids, vectors, holders)
        print(f"{churn_ratio:>9.0%} {100*meta_ok/n:>11.1f}% {100*payload_ok/n:>11.1f}% "
              f"{100*e2e_ok/n:>11.1f}%   | còn đủ shard {100*ph['payload_phys']/n:5.1f}% "
              f"| còn anchor {100*ph['meta_phys']/n:5.1f}%")
        nf = max(ph["n_failed"], 1)
        rows.append({"loss": churn_ratio, "metadata": 100 * meta_ok / n,
                     "payload": 100 * payload_ok / n, "e2e": 100 * e2e_ok / n,
                     # ppna-r1 đợt 1: tách mất shard với không tìm thấy shard
                     "metadata_physical": 100 * ph["meta_phys"] / n,
                     "payload_physical": 100 * ph["payload_phys"] / n,
                     "payload_lookup_miss": 100 * ph["lookup_miss"] / n,
                     "mean_alive_shards": ph["alive_sum"] / n,
                     "mean_found_shards_when_failed": ph["found_failed_sum"] / nf,
                     "mean_alive_shards_when_failed": ph["alive_failed_sum"] / nf})

    if OUT_JSON:
        import json
        extra = {}
        if JOIN_REFRESH > 0:
            extra["join_refresh"] = _refresh
        if KILL_FROM:
            extra["kills_from"] = KILL_FROM
        if JOIN_REFRESH > 0 and REFRESH_CACHE:
            extra["refresh_cache"] = REFRESH_CACHE
            extra["refresh_cache_loaded"] = _refresh_loaded
        if RECORD_KILLS:
            extra["killed_hex"] = killed_hex
        with open(OUT_JSON, "w") as fh:
            json.dump({"dataset": DATASET, "r": METADATA_ANCHORS, "nodes": NUM_NODES,
                       "num_files": NUM_FILES, "sample": n,
                       "routing_table": _netmod.ROUTING_TABLE,
                       "bootstrap": _netmod.BOOTSTRAP, "net_seed": NET_SEED,
                       "sample_seed": SAMPLE_SEED,
                       "ingest_sample_only": INGEST_SAMPLE_ONLY,
                       "contacts_mean": float(np.mean(_contacts)),
                       "contacts_min": int(np.min(_contacts)),
                       "churn_steps": CHURN_STEPS,
                       "commit": _os.environ.get("RUN_COMMIT", ""),
                       "rows": rows, **extra}, fh, indent=2)
        print(f"-> Lưu: {OUT_JSON}")


if __name__ == "__main__":
    if NET_SEED is not None:
        from src.routing import initialize_lsh_projections
        random.seed(int(NET_SEED))
        np.random.seed(int(NET_SEED) % (2**32))
        initialize_lsh_projections(int(NET_SEED))
    env = simpy.Environment()
    env.process(run_churn_test(env))
    env.run()