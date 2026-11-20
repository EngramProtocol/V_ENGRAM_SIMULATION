# Đợt 3: phần iterative còn lại (tag `ppna-r1-dot3`)

## Mục đích

Hoàn tất các thí nghiệm iterative của kế hoạch sửa (R1-2, R1-4, R1-5) và hai phần thêm đề
xuất trong báo cáo đợt 2. Cùng 10 seed với đợt 1 và đợt 2; cùng script
`ppna_r1/dot2/iterative.py` (dựng mạng một lần cho mỗi (seed, corpus), chạy nhiều biến thể
truy vấn trên mạng đó).

| Nhóm | Số job | Nội dung | Nhận xét |
|---|---|---|---|
| tk | 10 | Bảng 5 trên iterative (code): T ∈ {1, 3, 5, 12} với K = 20; K ∈ {10, 40, 80} với T = 8 | R1-2 |
| ws50 | 10 | 50.000 peer (code100k): K = 100 (= N/500) và K = 20 | R1-2, R1-3 |
| wl | 40 | Workload R1-4 trên iterative: SQuAD, e5 code, e5 SciFact, jina code (896 chiều, PQ m = 448); semantic và random equal peers | R1-4 |
| ref | 20 | Join đầy đủ như Kademlia gốc: sau join, mỗi peer làm mới mọi k-bucket xa hơn láng giềng gần nhất (tra một ID ngẫu nhiên trong vùng mỗi bucket); hai vòng, sau mỗi vòng chạy cấu hình chính, full round budget và truy vấn oracle | R1-2, R2-1 |
| lshf | 20 | Bucket-LSH với ingest chạy hết ngân sách (exhaust/all, R_max 15), T = 8, b chọn trên validation ở đợt 1 | R1-5 |
| sem_r, lsh_r, loss_r, ws25_r, ws50_r, tk_r, wl_r | 120 | Bản sao mọi thí nghiệm iterative của đợt 2 và đợt 3 với join đầy đủ (join + một vòng làm mới k-bucket) | R1-2 |

Tổng 220 job.

Join của simulator (từ trước bản đã nộp) gồm một lượt gia nhập tuần tự và một vòng tra lại
chính mình, nhưng thiếu bước làm mới bucket mà bài báo Kademlia mô tả ("refreshes all k-buckets
further away than its closest neighbor"). Đợt 2 cho thấy khoảng cách 5,2 điểm giữa hai mô hình
nằm ở bảng định tuyến chưa đầy; nhóm ref đo xem bước làm mới chuẩn lấy lại bao nhiêu. Vòng làm
mới dùng bộ sinh số riêng, nên các ô ghép cặp được với cấu hình chính của đợt 2.

Kiểm một seed trên máy thử (20235956, code): sau một vòng làm mới, cấu hình chính đạt R@5 82,44,
đúng bằng ô toàn oracle của đợt 2 cùng seed (join cũ: 76,44), với ít RPC hơn (991 so với 1.322);
frontier stability, full round budget và truy vấn oracle cho cùng recall. Nếu kết quả này giữ ở
10 seed, thầy có thể chọn dùng join đầy đủ cho mọi số iterative của bài. Vì vậy đợt 3 chạy luôn
bản sao của mọi thí nghiệm iterative với join đầy đủ (các nhóm có hậu tố `_r`), để chọn cách nào
cũng không phải chạy thêm.

## Kiểm trước khi gửi

- Mọi kế hoạch mới chạy được ở quy mô nhỏ (smoke test 9/9 trên máy thử), kể cả jina 896 chiều.
- Biến thể base của nhóm tk trùng từng số với base của nhóm sem ở đợt 2 (seed 20235956, đo trên
  máy thử); báo cáo tổng hợp so lại đủ 10 seed (mục 1).
- Ở 10.000 peer, một vòng làm mới đưa số contact mỗi peer từ 45 lên 197, bằng bảng đầy đủ của
  đợt 2.

## Thay đổi code

- `src/network.py`: `refresh_buckets` (vòng làm mới k-bucket như Kademlia gốc).
- `ppna_r1/dot2/iterative.py`: kế hoạch `tk`, `wl`, `refresh`; `--join-refresh` (join đầy đủ cho
  mọi kế hoạch); `--pq` (jina dùng m448); `--ingest-rule` cho kế hoạch `lsh`; số chiều phép chiếu
  lấy từ embedding (với 1024 chiều trùng lời gọi cũ). Các kế hoạch của đợt 2 cho kết quả không đổi.
- `ppna_r1/dot3/`: danh sách job, script tổng hợp (so với đợt 2 và mô hình lý tưởng cùng seed).

## Điều kiện trước khi chạy

- Còn kết quả đợt 1 (`ppna_r1/out_dot1`) và đợt 2 (`ppna_r1/out_dot2`) trên server.
- Dữ liệu: code, scifact, code100k, squad, code_e5, scifact_e5, code_jina (đều đã có từ đợt 1).

## Trên laptop

```bash
cd ~/V_Engram_Simulation
git checkout main && git pull
git log --oneline -1          # ppna r1: dot 2, mo hinh iterative va phan tach khoang cach hai mo hinh
git am ~/Downloads/0005-ppna-r1-dot-3*.patch
sha256sum -c ppna_r1/SHA256SUMS_dot3         # mọi dòng OK
git tag -a ppna-r1-dot3 -m "ppna r1: dot 3"
git push origin main --tags
```

## Trên server

**1. Lấy code và chạy**

```bash
cd ~/V_ENGRAM_SIMULATION
tmux ls                                   # không còn phiên dot2
git status --short | grep -v '^??'        # không in gì
git fetch origin --tags && git checkout ppna-r1-dot3
sha256sum -c ppna_r1/SHA256SUMS_dot3
source venv/bin/activate
tmux new -s dot3 -d "bash ~/V_ENGRAM_SIMULATION/ppna_r1/run_dot3.sh"
```

**2. Sau khoảng 10 phút, kiểm smoke test**

```bash
cat ppna_r1/logs_dot3/smoke/check.txt       # dòng cuối: SMOKE CHECK: 9/9 đạt
tail -3 ppna_r1/logs_dot3/run.log           # đã sang phần chạy chính
```

Smoke lỗi thì script dừng; gửi thư mục `ppna_r1/logs_dot3/smoke`.

**3. Theo dõi và khi xong**

```bash
grep -c "XONG ĐỢT 3" ppna_r1/logs_dot3/run.log      # 1 là đã xong
ls ppna_r1/out_dot3/*/*.ok 2>/dev/null | wc -l       # đủ là 220
tail -2 ppna_r1/logs_dot3/run.log                    # job vừa xong, số job còn lại, thời gian ước
tail -15 ppna_r1/dot3_report.txt                     # khi xong: KẾT LUẬN: k vấn đề
tar czf ~/vengram_dot3.tar.gz ppna_r1/out_dot3 ppna_r1/logs_dot3 ppna_r1/dot3_report.txt ppna_r1/dot3_summary.json
sha256sum ~/vengram_dot3.tar.gz
```

**Thời gian ước:** khoảng 10 đến 13 giờ với 7 job song song (ước theo thời gian thật của đợt 2),
nên để chạy qua đêm. Smoke test khoảng 2 đến 5 phút. Hai mươi job 50.000 peer chạy trước, tối đa
4 job cùng lúc (mỗi job khoảng 3 GB RAM, 1 đến 1,5 giờ; job 25.000 peer ở đợt 2 đỉnh 1,5 GB); các
nhóm khác chạy ở các nhân còn lại. Chỉ chạy phần theo kế hoạch cũ (không có bản sao, khoảng 4 đến
5 giờ): đặt `RUN_GROUPS="tk ws50 wl ref lshf"` trước `bash`; phần còn lại chạy sau bằng chính lệnh
đó không có RUN_GROUPS.

## Khi cần

- **Bị ngắt:** chạy lại đúng lệnh tmux; job đã xong với cùng commit được bỏ qua.
- **Chạy riêng vài nhóm:** `RUN_GROUPS="tk ref"` đặt trước `bash`. Chỉ tổng hợp lại:
  `STAGES=report bash ppna_r1/run_dot3.sh`.
- **RAM thấp:** `BIG_PARALLEL=2` đặt trước `bash` để chỉ 2 job 50.000 peer chạy cùng lúc.
