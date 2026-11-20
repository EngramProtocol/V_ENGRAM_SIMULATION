# Đợt 2: mô hình iterative (tag `ppna-r1-dot2`)

## Mục đích

Chạy các thí nghiệm cần mô hình iterative (k-bucket dựng bằng join, ingest và truy vấn bằng
Ripple Search) cho nhận xét R1-2, R1-3, R1-5, R1-6, và hai phần nhỏ trên mô hình lý tưởng mà
báo cáo đợt 1 đề xuất. Cùng 10 seed với đợt 1 (20235956, 1 đến 9).

| Nhóm | Số job | Nội dung | Nhận xét |
|---|---|---|---|
| sem | 20 | Cấu hình chính (code, SciFact) và các biến thể chỉ đổi truy vấn: Bảng 7 (frontier stability all và top-K, exhaustive top-K, full round budget; R_max = 15 và 30), bốn control, margin ablation, (c = 9, T = 5), truy vấn oracle; code thêm mất 20% và 30% peer | R1-2, R1-1, R1-3, R1-6 |
| dec | 20 | Phân tách khoảng cách giữa hai mô hình: đặt record oracle, bảng định tuyến đầy đủ, ingest chạy hết ngân sách; mỗi cách dựng chạy truy vấn Ripple Search và truy vấn oracle | R1-2, R2-1 |
| lsh | 20 | Bucket-LSH trên overlay: khoá là băm của b bit đầu, mỗi probe một lookup, T = 8, b chọn trên validation ở đợt 1 (theo từng seed) | R1-5 |
| loss | 10 | r = 2 và 3 trên code: không mất peer và mất 30% peer | R1-2, R1-3 |
| ws | 10 | 25.000 peer (code50k), K = 50 và K = 20 trên cùng một mạng | R1-2, R1-3 |
| gpt | 20 | Lý tưởng: chiếu Gaussian kèm thống kê từng bảng chiếu, hai corpus | R1-1 |
| jina | 50 | Lý tưởng: jina-code-embeddings-0.5b với T = 12; K = 40, 80; L = 8; (L = 8, T = 5) | R1-4 |

Tổng 150 job. Phân tách khoảng cách dùng 2 × 2 × 2 ô: ô (thật, thật, thật) là cấu hình chính
và ô (thật, thật, truy vấn oracle) nằm trong nhóm sem, sáu ô còn lại và ô chỉ đổi ingest nằm trong
nhóm dec. Mọi ô của cùng một seed bắt đầu từ đúng một mạng sau join và cùng trạng thái bộ sinh số
ngẫu nhiên, nên so ghép cặp được.

## Cách chạy mới: dựng mạng một lần, chạy nhiều biến thể

Ở đợt kiểm 17/11, mỗi lần chạy iterative mất khoảng 19 phút, phần lớn cho join, ingest và việc
tính lại bảng tra ADC ở từng peer. Đợt 2 dùng `ppna_r1/dot2/iterative.py`: mỗi job dựng mạng một
lần cho một (seed, corpus) rồi chạy mọi biến thể truy vấn trên mạng đó. Trước mỗi biến thể, trạng
thái bộ sinh số ngẫu nhiên, đồng hồ mô phỏng và thống kê lookup được đặt lại đúng như ngay sau khi
dựng mạng, nên mỗi biến thể cho đúng kết quả của một lần chạy `main_simulation.py` riêng.

Đã kiểm trên máy:
- Với seed 20235956, cấu hình chính và ba biến thể Bảng 7 chỉ đổi truy vấn trùng từng trường
  (62 trường, gồm recall, RPC, độ trễ, thứ hạng XOR, vị trí record) với file của đợt kiểm 17/11
  (`out_verify_s2/C`). Báo cáo tổng hợp so lại cả năm seed của đợt kiểm đó trên server (mục 1).
- Ở quy mô nhỏ: `main_simulation.py` sau patch cho kết quả trùng từng trường với trước patch
  (semantic, keyed_lookup, random_slots); mọi biến thể của `iterative.py` trùng từng trường với
  lần chạy riêng tương ứng (cấu hình chính, exhaust/all, exhaust/topk với R_max = 30, lật bit ngẫu
  nhiên, hai control).

## Thay đổi code

Mọi tham số mới mặc định giữ hành vi cũ.

- `src/node.py`: `adc_lut` tính bảng tra ADC một lần cho mỗi query thay vì mỗi peer một lần
  (cùng phép tính, kết quả không đổi); nơi lưu record của Bucket-LSH.
- `src/network.py`: `query_pipeline_process` thêm truy vấn oracle (đúng K peer XOR-gần nhất thật),
  Bucket-LSH trên overlay, control random candidate threshold, random equal peers khớp theo từng
  query, c của truy vấn, danh sách peer còn sống, và một hàm đo mỗi lookup (trùng với K peer gần
  nhất thật, lookup trả ít hơn K peer, số vòng, thứ hạng XOR tính bằng numpy).
  `data_ingestion_process` thêm đặt record oracle và đặt theo bucket; mọi chế độ rút số ngẫu
  nhiên như nhau.
- `src/routing.py`: khoá DHT và các probe của Bucket-LSH.
- `src/oracle.py` (mới): chỉ mục XOR đúng tuyệt đối, bảng định tuyến đầy đủ từ thông tin toàn cục
  (bộ sinh số riêng), lưu và khôi phục bảng định tuyến, gỡ peer chết.
- `ppna_r1/dot2/`: `iterative.py`, danh sách job, script tổng hợp. Bộ chạy dùng lại
  `ppna_r1/dot1/runner.py`.

## Điều kiện trước khi chạy

- Đợt 1 đã xong và còn trên server: `ppna_r1/out_dot1` và `ppna_r1/dot1_summary.json`. Script tổng
  hợp so số iterative với số lý tưởng cùng seed, và kiểm b_LSH ghi trong `jobs.py` khớp lựa chọn của
  đợt 1.
- Còn `ppna_r1/out_verify_s2/C` của đợt kiểm 17/11 (để so hồi quy). Thiếu thì chỉ bỏ phần so đó.
- Dữ liệu: code, scifact, code50k, code100k (smoke test đo 50.000 peer), code_jina.

## Trên laptop

```bash
cd ~/V_Engram_Simulation
git checkout main && git pull
git log --oneline -1          # ppna r1: nhung model bang float32, dot 1 chay truoc khi co e5 va jina
git am ~/Downloads/0004-ppna-r1-dot-2*.patch
sha256sum -c ppna_r1/SHA256SUMS_dot2         # mọi dòng OK
git tag -a ppna-r1-dot2 -m "ppna r1: dot 2"
git push origin main --tags
```

## Trên server

**1. Lấy code**

```bash
cd ~/V_ENGRAM_SIMULATION
git status --short | grep -v '^??'      # không in gì
git fetch origin --tags && git checkout ppna-r1-dot2
sha256sum -c ppna_r1/SHA256SUMS_dot2
ls ppna_r1/out_dot1 ppna_r1/dot1_summary.json ppna_r1/out_verify_s2/C | head -3
```

**2. Chạy**

```bash
[ -f venv/bin/activate ] && source venv/bin/activate
tmux new -s dot2 -d "bash ~/V_ENGRAM_SIMULATION/ppna_r1/run_dot2.sh"
```

Mặc định chạy `nproc − 1` job song song. Đổi bằng `PARALLEL=6` đặt trước `bash`.

**Thời gian ước:** smoke test khoảng 5 đến 10 phút; cả đợt khoảng 3 đến 4 giờ với 7 job song song
(đo trên máy thử: một job sem code 14 phút, dec code 11 phút, lsh code 2 phút, dùng tối đa khoảng
1 GB RAM; đã nhân hệ số 1,8 đo được ở đợt 1). Job dài nhất là sem code và 25.000 peer.

**Kiểm sau khoảng 10 phút** (smoke test đã xong):

```bash
cat ppna_r1/logs_dot2/env.txt | tail -3     # dòng "b_LSH: khớp dot1_summary.json"
cat ppna_r1/logs_dot2/smoke/check.txt       # dòng cuối: SMOKE CHECK: 9/9 đạt
tail -3 ppna_r1/logs_dot2/run.log           # đã sang phần chạy chính
```

`check.txt` in thêm thời gian và bộ nhớ đo ở 25.000 và 50.000 peer (để lập lịch đợt 3). Smoke test
lỗi thì script dừng; gửi thư mục `ppna_r1/logs_dot2/smoke`.

**Theo dõi:** `tail -5 ppna_r1/logs_dot2/run.log`. Mỗi dòng ghi job vừa xong, mã thoát, số job còn
lại và thời gian ước.

**Khi xong** (`run.log` có dòng `XONG ĐỢT 2`):

```bash
tail -15 ppna_r1/dot2_report.txt        # dòng "KẾT LUẬN: k vấn đề"
tar czf ~/vengram_dot2.tar.gz ppna_r1/out_dot2 ppna_r1/logs_dot2 ppna_r1/dot2_report.txt \
    ppna_r1/dot2_summary.json
sha256sum ~/vengram_dot2.tar.gz
```

## Khi cần

- **Bị ngắt:** chạy lại đúng lệnh tmux. Job đã xong với cùng commit được bỏ qua; job đang dở
  chạy lại từ đầu (mỗi job dài nhất khoảng nửa giờ).
- **Chạy riêng vài nhóm:** `RUN_GROUPS="sem dec"` đặt trước `bash`. Chỉ tổng hợp lại:
  `STAGES=report bash ppna_r1/run_dot2.sh`.
- **Không chạy job nặng khác** trên server trong lúc chạy.
