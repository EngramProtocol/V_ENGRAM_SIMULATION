# Đợt 4: L = 8 bảng trên mô hình iterative (tag `ppna-r1-dot4`)

## Mục đích

Mục chọn điểm vận hành (R2-2) dự kiến đưa cấu hình L = 8, T = 5: cùng 40 target với cấu hình chính
nhưng hơn khoảng 6,7 điểm trên mô hình lý tưởng (đợt 1), đổi lại 8 record mỗi object thay vì 5.
Cấu hình này mới có số lý tưởng. Đợt 4 đo nó trên mô hình iterative để mọi điểm vận hành trong bảng
đều có số của giao thức thật:

- `lt`: iterative, join đầy đủ (join cũ cộng một vòng làm mới k-bucket như Kademlia gốc), L = 8,
  biến thể T = 8 và T = 5 trên cùng một mạng.
- `lt_old`: như trên với join cũ, cho phân tích độ nhạy theo join như mọi bảng iterative khác.
- `r11_L8`: chạy lại đúng hai job lý tưởng L8 và L8_T5 của đợt 1 (cùng lệnh, cùng seed) để ghép
  cặp iterative với lý tưởng theo seed và kiểm hồi quy với số của đợt 1.

Các tham số khác như cấu hình chính: N = 10.000, K = 20, c = 16, r = 1, PQ m = 512, κ = 30, 500
query, Ripple Search stable/all, R_max = 15. Code và SciFact, 10 seed: 80 job.

## Thay đổi code

`ppna_r1/dot2/iterative.py` nhận `--num-tables` (mặc định 5, giữ nguyên mọi kế hoạch cũ) và có kế
hoạch `lt`. Số bảng phải đặt trước khi import `src.*`, vì `src.routing` đọc `NUM_TABLES` lúc import;
file kết quả ghi số bảng trong `env.NUM_TABLES`.

## Chạy

```bash
cd ~/V_ENGRAM_SIMULATION
git fetch origin --tags && git checkout ppna-r1-dot4
sha256sum -c ppna_r1/SHA256SUMS_dot4
source venv/bin/activate
tmux new -s dot4 -d "bash ~/V_ENGRAM_SIMULATION/ppna_r1/run_dot4.sh"
```

Theo dõi: `tail -3 ppna_r1/logs_dot4/run.log`; xong khi có dòng `XONG ĐỢT 4`. Kết quả:
`ppna_r1/out_dot4`, `ppna_r1/dot4_report.txt`, `ppna_r1/dot4_summary.json`.

**Thời gian ước:** khoảng 13 giờ một nhân, tức khoảng 2 giờ trên server 8 nhân với 7 job song song.
Job lý tưởng chạy trước, rồi join đầy đủ, rồi join cũ.
