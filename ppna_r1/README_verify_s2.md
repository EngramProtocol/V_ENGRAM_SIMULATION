# Kiểm các vấn đề Mục 2.1–2.4 (tag `ppna-r1-verify-s2`)

## Mục đích

Chạy lại các thí nghiệm liên quan tới bốn vấn đề ở Mục 2 của tài liệu định hướng sửa bài, để biết vấn đề có thật không và số trong bài đổi bao nhiêu, trước khi gửi thầy.

| Nhóm | Mục | Làm gì | Số job |
|---|---|---|---|
| A | 2.1, 2.2, 2.4 | Đọc file kết quả cũ trên server, không chạy gì. In ra `ppna_r1/verify_s2_partA.txt` ngay từ đầu | 0 |
| B | 2.1 | Chạy đủ 10 seed cho các hàng chỉ có 5 seed: Bảng 5 (T = 1, T = 12, K = 10, 40, 80) và hàng candidate threshold của Bảng 4 (hai corpus). Dùng code chưa chuẩn hoá như bản đã nộp, nên seed 20235956, 1 đến 4 phải trùng từng số với file cũ | 70 |
| C | 2.2, 2.3 | Mô hình iterative (k-bucket, join), 5 seed. `main`: cấu hình chính. `q_<X>`: join và ingest giữ stable/all, chỉ truy vấn đổi sang X. `b_<X>`: dựng mạng và ingest theo X ở mọi pha, đo vị trí record và bảng định tuyến, không chạy truy vấn | 35 |
| D | 2.4 | Availability (`main_churn_test.py`) trên overlay k-bucket có join và seed, r = 1, 2, 3, mất 0/10/20/30% peer, 10 seed; thêm overlay ring 3 seed để đối chiếu | 39 |

Trước các nhóm B, C, D, script chạy một smoke test thu nhỏ của mọi kiểu job (khoảng 1 phút). Nếu smoke test lỗi, script dừng và không tốn giờ máy.

## Thay đổi code

Đây là lần đầu code mô phỏng đổi kể từ bản đã nộp. Mọi cờ mới mặc định tắt.

- `src/routing.py`: quy tắc dừng riêng cho từng pha (`JOIN_STOP_RULE`, `JOIN_FRONTIER_SCOPE`, `JOIN_R_MAX`, `INGEST_*`); đếm số vòng, RPC và lý do dừng của lookup theo pha; `OVERLAP_STATS=0` tắt phép đo overlap tốn thời gian cho lookup lúc ingest.
- `src/network.py`: gắn nhãn pha cho mọi lookup; `DIAG_BUILD=1` ghi anchor đã chọn lúc ingest; `data_ingestion_process` nhận thêm `doc_ids`.
- `src/diag.py` (mới): đo tỉ lệ record đặt đúng tại peer XOR-gần nhất, thứ hạng XOR toàn cục của anchor, và tỉ lệ bảng định tuyến chứa 20 peer gần nhất thật.
- `main_simulation.py`: `BUILD_ONLY=1`; ghi quy tắc từng pha, thống kê lookup và chẩn đoán vào JSON.
- `main_churn_test.py`: `NET_SEED` (bản cũ không đặt seed khi dựng mạng); gỡ peer chết khỏi k-bucket, vì lookup trên k-bucket đọc bucket chứ không đọc `routing_table`; `INGEST_SAMPLE_ONLY=1` chỉ ingest 500 object được đo; `PQ_VARIANT`; `OUT_JSON`.

Đã kiểm trên dữ liệu thật ở quy mô nhỏ: với cấu hình mặc định, code vá cho kết quả trùng từng trường với code cũ ở stable/all, exhaust/all, stable/topk, overlay ring, và khi đặt tường minh `JOIN_*`/`INGEST_*` bằng quy tắc truy vấn; `main_churn_test.py` trên ring với cùng seed cho log trùng từng dòng.

## Trên laptop

```bash
cd ~/V_Engram_Simulation
git checkout main && git pull
git log --oneline -1                     # phải là: ppna r1: verify norm, kiem chuan hoa cot chieu
git am ~/Downloads/0001-ppna-r1-verify-s2*.patch
sha256sum -c ppna_r1/SHA256SUMS_verify_s2     # mọi dòng OK (máy Mac: shasum -a 256 -c ...)
git tag -a ppna-r1-verify-s2 -m "ppna r1: kiem muc 2.1-2.4"
git push origin main --tags
```

## Trên server

```bash
cd ~/V_ENGRAM_SIMULATION
git status --short | grep -v '^??'      # không in gì
git fetch origin --tags && git checkout ppna-r1-verify-s2
git describe --tags                      # ppna-r1-verify-s2
sha256sum -c ppna_r1/SHA256SUMS_verify_s2
nproc; free -g                           # chọn PARALLEL: số nhân trừ 1, mỗi job cần khoảng 0,5 đến 1 GB RAM
[ -f venv/bin/activate ] && source venv/bin/activate
tmux new -s verifys2 -d "PARALLEL=4 bash ~/V_ENGRAM_SIMULATION/ppna_r1/run_verify_s2.sh"
```

**Thời gian ước tính** (đo trên một nhân): job iterative đầy đủ khoảng 20 phút, job `b_` khoảng 2 phút, job availability khoảng 3 phút, job nhóm B khoảng 30 giây. Với `PARALLEL=4` cả đợt mất khoảng 2 đến 2,5 giờ; nhóm C chiếm phần lớn.

**Kiểm sau khoảng 5 phút:**

```bash
cat ppna_r1/logs_verify_s2/env.txt         # mục file đã track bị sửa phải trống
grep "smoke" ppna_r1/logs_verify_s2/run.log 2>/dev/null; tmux capture-pane -pt verifys2 | tail -5
cat ppna_r1/verify_s2_partA.txt            # kết quả nhóm A, gửi trước được
```

**Theo dõi:** `head -1 ppna_r1/logs_verify_s2/run.log` cho tổng số job; `grep -c "mã thoát" ppna_r1/logs_verify_s2/run.log` cho số job đã xong.

**Khi xong** (dòng cuối `run.log` là `XONG KIỂM MỤC 2`):

```bash
grep "mã thoát [1-9]" ppna_r1/logs_verify_s2/run.log     # không in gì
find ppna_r1/out_verify_s2 -name '*.ok' | wc -l           # bằng tổng số job (mặc định 144)
tar czf ~/vengram_verify_s2.tar.gz ppna_r1/out_verify_s2 ppna_r1/logs_verify_s2 \
    ppna_r1/snap_existing ppna_r1/verify_s2_partA.txt ppna_r1/verify_s2_report.txt
sha256sum ~/vengram_verify_s2.tar.gz
```

Lấy file về laptop bằng `scp` như mọi lần, rồi gửi file tar.gz.

Nếu tmux bị ngắt, chạy lại đúng lệnh tmux ở trên: job đã xong với cùng commit được bỏ qua. Muốn chạy riêng một nhóm: đặt `RUN_GROUPS="C"` trước `bash`.

## Cách đọc `verify_s2_report.txt`

- **A1:** seed có trên đĩa và trung bình năm seed của các hàng 5 seed. Nếu trùng số in trong bài thì bài đang in trung bình năm seed.
- **A2:** số seed, thời điểm ghi và phiên bản phép chiếu của Bảng 8, 9. Dòng `repl_r1 so với đợt kiểm chuẩn hoá` cho biết hai bảng này dùng code đã hay chưa chuẩn hoá.
- **A3:** tỉ lệ lookup truy vấn chạy hết R_max trong file Bảng 7 cũ. Mục 2.2 đúng nếu hàng exhaust-all là 100%.
- **A4:** từng log availability dựng trên overlay nào và ghi trước hay sau ngày có code k-bucket.
- **A5:** Bảng 6 ghi trước hay sau mốc chuẩn hoá.
- **B:** cột `hồi quy` phải là 5/5 trùng; `dịch` là mức đổi khi đủ 10 seed.
- **C0:** cấu hình chính chạy bằng code vá phải trùng file Bảng 7 cũ ở mọi trường.
- **C1:** cột `phần do dựng+ingest` là phần chênh của Bảng 7 không đến từ quy tắc dừng lúc truy vấn. Bảng thứ hai so mức chênh như bài báo cáo với mức chênh khi chỉ đổi truy vấn.
- **C2:** tỉ lệ record đặt đúng peer gần nhất và độ đầy bảng định tuyến theo từng biến thể.
- **D:** availability trên k-bucket so với số in trong Bảng 9 và so với ring trên cùng seed.

Đợt này không đổi file kết quả cũ nào; mọi kết quả mới nằm trong `ppna_r1/out_verify_s2/`, file cũ được chép (giữ thời điểm ghi) vào `ppna_r1/snap_existing/`.
