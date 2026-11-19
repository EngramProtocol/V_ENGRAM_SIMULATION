# Đợt 1: mô hình lý tưởng, availability và churn (tag `ppna-r1-dot1`)

## Mục đích

Sinh lại bằng **một commit và cùng 10 seed** (20235956, 1 đến 9) mọi số của bản đã nộp
không cần mô hình iterative, và chạy các thí nghiệm mới cho nhận xét của reviewer.
Phần iterative (Bảng 7, phân tách khoảng cách giữa hai mô hình, control và Bucket-LSH
iterative, peer loss iterative) thuộc đợt 2.

| Nhóm | Số job | Nội dung | Nhận xét |
|---|---|---|---|
| t4 | 100 | Bảng 4: semantic và bốn control, hai corpus; hàng semantic ghi thêm thống kê từng bảng chiếu | R1-3 |
| t5 | 70 | Bảng 5: T ∈ {1, 3, 5, 12} với K = 20; K ∈ {10, 40, 80} với T = 8 | R1-3 |
| t8 | 80 | Bảng 8: r ∈ {2, 4, 5, 10}, semantic và random nominal (10 seed cho cả control) | R1-3 |
| loss | 220 | Bảng 9 và hình: Final R@5 khi mất 5 đến 50% peer (bước 5%), r = 1 và 2; r = 3 ở 0% và 30% | R1-3 |
| avail | 30 | Bảng 9 và hình: availability trên k-bucket có join, r = 1, 2, 3, mất 0 đến 50% peer; tách shard đã mất với shard còn sống mà lookup không tìm thấy | R1-3 |
| regress | 3 | Availability seed 20235956 đúng lệnh đợt kiểm 17/11, phải trùng từng số | kiểm |
| churn | 30 | Bảng 10: ba cấu hình, 10 seed | R1-3 |
| kappa | 60 | κ ∈ {10, 50, 100} (câu về κ ở Mục 4.1) | nhất quán |
| val | 20 | V-Engram trên 500 query validation mỗi corpus | R1-5 |
| lsh | 120 | Bảng 6: Bucket-LSH với cùng PQ m = 512 và cùng phép chiếu như V-Engram, quét b = 8 đến 16, T ∈ {1, 4, 8}, trên validation và test | R1-5 |
| ws | 140 | Bảng 11, 12, hình 4: weak scaling 15k, 20k, 25k, 35k, 50k peer, K = 20 và K = N/500; control random nominal ở 25k và 50k | R1-3 |
| r11 | 680 | R1-1: Gaussian; PQ m ∈ {64, 128, 256} và không PQ; L ∈ {3, 4, 6, 8, 10}; (L = 8, T = 5); c ∈ {8, 9, 12, 24}; (c = 9, T = 5); (c = 12, T = 6); hai corpus, mỗi điểm kèm control random equal peers | R1-1, R1-6 |
| r14 | 200 | R1-4: SQuAD, e5-large-v2 (code, SciFact), jina-code-embeddings-0.5b (code); semantic và bốn control | R1-4 |
| trunc | 120 | Khoá cụt b ∈ {8, 10, 12, 16} bit ở 10k, 25k, 50k peer, K = 20 | R1-5, R1-7 |
| coll | 2 | Tỉ lệ trùng bit theo góc, Achlioptas và Gaussian, so với 1 − θ/π | R1-1 |

Tổng 1.875 job, ước khoảng 40 giờ một nhân, tức **khoảng 6 đến 8 giờ với 7 job song song**.
Job dài nhất là availability và weak scaling 50.000 peer, mỗi job vài phút đến khoảng 10 phút.

`ppna_r1/dot1/predictions_dot1.json` ghi dự đoán của mô hình chi phí cho mọi cấu hình
**trước khi chạy** (commit cùng patch), để báo cáo so dự đoán với số đo (R1-6).

## Thay đổi code

Các cờ mới mặc định tắt. Đã kiểm trên máy: cấu hình chính, Bucket-LSH và availability
cho kết quả trùng từng số với code trước patch. Báo cáo tổng hợp kiểm lại trên server
(mục 1 của `dot1_report.txt`).

- `main_simulation_v2.py`: `--query-set val`, `--key-bits B` (khoá cụt), `--proj-family gaussian`;
  mọi L sinh ma trận bằng cùng một hàm và cùng chuẩn hoá cột (bản trước sinh L > 5 ở nhánh
  riêng không chuẩn hoá); JSON ghi đủ cấu hình, commit và tương quan cặp bảng.
- `src/routing.py`: họ Gaussian; cột Achlioptas toàn 0 được sinh lại như Mục 3.1 viết.
- `baselines.py`: Bucket-LSH đọc corpus, biến thể PQ và tập query qua biến môi trường,
  chế độ `BUCKET_ONLY=1` chỉ quét bucket và ghi JSON.
- `main_churn_test.py`: với mỗi object đếm shard còn sống và shard lookup tìm thấy.
- `main_churn_engine.py`: ghi commit vào JSON.
- `ppna_r1/dot1/`: danh sách job, bộ chạy song song, script tổng hợp, phân tích trùng bit.

## Điều kiện trước khi chạy

- Bước chuẩn bị dữ liệu (`ppna-r1-prep`) đã xong: dòng cuối `ppna_r1/prep_report.txt` là `KẾT LUẬN: 0 lỗi`.
- Dữ liệu cũ vẫn ở `data/`: code, scifact, squad, code50k, code100k.
- Nên còn `ppna_r1/out_verify_norm`, `ppna_r1/out_verify_s2` và các file `churn_code_N10000_*.json`
  của bản đã nộp: script tổng hợp dùng chúng để so hồi quy. Thiếu thì chỉ bỏ phần so đó.

## Trên laptop

```bash
cd ~/V_Engram_Simulation
git checkout main && git pull
git log --oneline -1                     # phải là: ppna r1: chuan bi du lieu dot 1 tren server (thay Colab)
git am ~/Downloads/0002-ppna-r1-dot-1*.patch
sha256sum -c ppna_r1/SHA256SUMS_dot1     # mọi dòng OK
git tag -a ppna-r1-dot1 -m "ppna r1: dot 1"
git push origin main --tags
```

## Trên server

**1. Lấy code** (sau khi bước chuẩn bị dữ liệu đã xong)

```bash
cd ~/V_ENGRAM_SIMULATION
git status --short | grep -v '^??'      # không in gì
git fetch origin --tags && git checkout ppna-r1-dot1
sha256sum -c ppna_r1/SHA256SUMS_dot1
tail -1 ppna_r1/prep_report.txt          # KẾT LUẬN: 0 lỗi
free -g; df -h .                         # cần trống khoảng 2 GB đĩa
```

**2. Chạy**

```bash
[ -f venv/bin/activate ] && source venv/bin/activate
tmux new -s dot1 -d "bash ~/V_ENGRAM_SIMULATION/ppna_r1/run_dot1.sh"
```

Script tự dùng `venv/bin/python` nếu có. Mặc định chạy `nproc − 1` job song song; overlay
từ 35.000 peer trở lên chạy tối đa 3 job cùng lúc và chỉ khởi động khi RAM trống còn
từ 3 GB. Đổi bằng `PARALLEL=6`, `BIG_PARALLEL=2`, `MIN_FREE_GB=4` đặt trước `bash`.

**Kiểm sau khoảng 10 phút** (smoke test đã xong):

```bash
cat ppna_r1/logs_dot1/smoke/check.txt    # dòng cuối: SMOKE CHECK: 23/23 đạt
tail -3 ppna_r1/logs_dot1/run.log        # đã sang phần chạy chính, có số job và thời gian ước
```

Smoke test lỗi thì script dừng; gửi thư mục `ppna_r1/logs_dot1/smoke`.

**Theo dõi:** `tail -5 ppna_r1/logs_dot1/run.log`. Mỗi dòng ghi job vừa xong, mã thoát,
số job còn lại và thời gian ước. Job lỗi có dòng `xem ...log`.

**Khi xong** (dòng cuối `run.log` là `XONG ĐỢT 1`):

```bash
tail -15 ppna_r1/dot1_report.txt         # dòng "KẾT LUẬN: k vấn đề" và danh sách vấn đề
tar czf ~/vengram_dot1.tar.gz ppna_r1/out_dot1 ppna_r1/logs_dot1 ppna_r1/dot1_report.txt \
    ppna_r1/dot1_summary.json
sha256sum ~/vengram_dot1.tar.gz
```

Gửi file tar.gz (khoảng 5 đến 10 MB).

## Khi cần

- **Bị ngắt** (mất điện, tmux đóng): chạy lại đúng lệnh tmux ở trên. Job đã xong với cùng
  commit được bỏ qua; job đang dở chạy lại từ đầu.
- **Chạy riêng vài nhóm:** `RUN_GROUPS="t4 lsh val"` đặt trước `bash`. Chỉ tổng hợp lại:
  `STAGES=report bash ppna_r1/run_dot1.sh`.
- **Một bước chuẩn bị dữ liệu bị lỗi** (ví dụ jina): smoke test sẽ báo thiếu dữ liệu.
  Báo lại; nếu cần chạy trước phần còn lại thì dùng `STAGES="run report"`, các job thiếu
  dữ liệu được bỏ qua và liệt kê trong `run.log`.
- **Không chạy job nặng khác** trên server trong lúc chạy: mỗi job chiếm một nhân.
