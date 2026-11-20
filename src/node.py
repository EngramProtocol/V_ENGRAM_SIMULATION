import random
import numpy as np


def adc_lut(query_vector, codebook):
    """Bảng tra ADC của một query: khoảng cách L2 bình phương từ từng đoạn query
    tới từng centroid. ppna-r1 đợt 2: tính một lần cho mỗi query rồi dùng lại cho
    mọi peer, thay vì mỗi peer tính lại. Cùng phép tính, cùng thứ tự, nên cho đúng
    từng bit như adc_search tự tính."""
    m, _, d_sub = codebook.shape
    query_subvectors = np.asarray(query_vector, dtype=np.float32).reshape(m, d_sub)
    diff = query_subvectors[:, np.newaxis, :] - codebook
    return np.sum(diff**2, axis=2)


class VEngramNode:
    def __init__(self, env, node_id):
        self.kbuckets = {}      # k-bucket: index -> list peer
        self.env = env
        self.node_id = node_id
        self.RAM_Index = {}
        self.SSD_Storage = {}
        self.routing_table = set()
        # ppna-r1 đợt 2: Bucket-LSH trên overlay iterative. (bảng, nhãn bucket) -> {tag: PQ code}
        self.BUCKETS = {}

    def store_bucket(self, bucket_id, object_tag, pq_code):
        """Bucket-LSH: lưu record dưới nhãn bucket của nó (không trộn với RAM_Index)."""
        self.BUCKETS.setdefault(bucket_id, {}).setdefault(object_tag, pq_code)

    def ping(self, target_node):
        yield self.env.timeout(random.uniform(10, 100))
        self.routing_table.add(target_node)

    def get_neighbors(self):
        return list(self.routing_table)

    # ---------------- k-bucket Kademlia ----------------
    # Bảng định tuyến phân tầng theo tiền tố XOR: bucket i giữ các peer có
    # khoảng cách XOR trong [2^i, 2^(i+1)), tối đa K_BUCKET peer mỗi bucket.
    # Đây là cấu trúc mà bài mô tả; nhánh ring giữ lại để đối chiếu.
    def kb_index(self, other_id):
        d = self.node_id ^ other_id
        return d.bit_length() - 1 if d else 0

    def kb_add(self, peer, k_bucket=20):
        if peer.node_id == self.node_id:
            return
        i = self.kb_index(peer.node_id)
        b = self.kbuckets.setdefault(i, [])
        if peer in b:
            b.remove(peer); b.append(peer)      # LRU: mới dùng đẩy về cuối
        elif len(b) < k_bucket:
            b.append(peer)
        # bucket đầy: Kademlia giữ peer cũ nếu còn sống. Ở đây peer không chết
        # trong lúc bootstrap nên bỏ qua, và ta KHÔNG thay peer cũ.

    def kb_closest(self, key, count):
        """Trả count peer gần key nhất trong bảng, gom từ mọi bucket."""
        allp = [p for b in self.kbuckets.values() for p in b]
        allp.sort(key=lambda p: p.node_id ^ key)
        return allp[:count]

    def store_metadata(self, object_tag, pq_code):
        """TẦNG 1 (Metadata): neo PQ code (phục vụ ADC rerank) vào RAM.
        Được nhân bản tại các node gần MỖI semantic key trong L key của object."""
        if object_tag not in self.RAM_Index:
            self.RAM_Index[object_tag] = pq_code

    def store_payload_shard(self, object_tag, shard_id, virtual_payload):
        """TẦNG 2 (Payload): lưu MỘT mảnh Reed-Solomon xuống đĩa.
        Mỗi object chỉ đặt một bộ shard (không nhân theo L)."""
        shard_key = f"{object_tag}_shard_{shard_id}"
        self.SSD_Storage[shard_key] = virtual_payload

    def store_shard(self, object_tag, shard_id, pq_code, virtual_payload):
        """[Giữ cho tương thích ngược - không dùng trong pipeline two-tier mới]"""
        self.store_metadata(object_tag, pq_code)
        self.store_payload_shard(object_tag, shard_id, virtual_payload)
        
    def adc_search(self, query_vector, codebook, top_k=5, lut=None):
        """
        GIAI ĐOẠN 3: TÍNH ADC THỰC TẾ TRÊN RAM.
        Sử dụng Bảng mã Codebook (m, 256, d_sub) và mã PQ uint8.
        lut: bảng tra đã tính sẵn bằng adc_lut cho query này (ppna-r1 đợt 2).
        """
        candidates = []
        if not self.RAM_Index:
            return candidates

        # Đọc m, d_sub TỪ codebook thay vì hardcode -> hỗ trợ mọi biến thể PQ
        # (m=256/d_sub=4 = 256 byte/doc; m=512/d_sub=2 = 512 byte/doc, sai số ~10x nhỏ hơn)
        m, _, d_sub = codebook.shape

        # BƯỚC 1-2: Bảng tra cứu (Look-Up Table): khoảng cách từ từng đoạn của
        # query tới từng centroid. Cùng phép tính với adc_lut.
        LUT = adc_lut(query_vector, codebook) if lut is None else lut

        # BƯỚC 3: Duyệt qua RAM Index và tra bảng
        for tag, pq_code in self.RAM_Index.items():
            # pq_code là mảng 256 con số nguyên (0-255).
            # Thay vì nhân vector, ta chỉ cộng 256 con số lấy từ LUT
            dist = np.sum(LUT[np.arange(m), pq_code])
            candidates.append((tag, dist))
            
        candidates.sort(key=lambda x: x[1])
        return candidates[:top_k]

    def get_shard(self, shard_key):
        yield self.env.timeout(random.uniform(2, 8))
        return self.SSD_Storage.get(shard_key, None)