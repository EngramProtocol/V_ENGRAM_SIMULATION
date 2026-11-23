# Đợt 6: availability của Bảng 9 với join đầy đủ (tag `ppna-r1-dot6`)

## Mục đích

Hai cột availability của Bảng 9 (metadata định tuyến được và payload giải mã được khi mất peer tĩnh) đo
bằng `main_churn_test.py` trên overlay k-bucket. Ở đợt 1, overlay này dựng bằng `bootstrap_network`, tức
join cũ: gia nhập tuần tự và một lần tra lại chính mình, không có bước làm mới k-bucket của Kademlia. Đợt 3
cho thấy join cũ để bảng định tuyến thiếu (khoảng 45 contact mỗi peer thay vì 197) và đó là nguồn của
khoảng cách recall giữa giao thức và mô hình lý tưởng. Ở đợt 1, 10,9 đến 12,4 điểm payload mất vì shard
còn sống nhưng lookup không tìm thấy. Đợt 6 đo lại hai cột này với join đầy đủ để xem phần đó có cùng
nguồn hay không, và để mọi số trên overlay k-bucket dùng cùng một join.

## Thay đổi trong `main_churn_test.py`

Bốn biến môi trường mới; không đặt thì hành vi như cũ:

- `JOIN_REFRESH=n`: sau `bootstrap_network`, chạy n vòng `refresh_buckets` (làm mới mọi k-bucket xa hơn
  láng giềng gần nhất, như join của Kademlia gốc), cùng bộ sinh số với `--join-refresh` của
  `ppna_r1/dot2/iterative.py`. Vòng làm mới không đụng `random` của Python.
- `RECORD_KILLS=1`: ghi ID các peer bị tắt ở từng mức mất vào file kết quả (`killed_hex`). Không dùng thêm
  số ngẫu nhiên nào, nên mọi số đo trùng lần chạy không ghi.
- `KILL_FROM=<file json>`: tắt đúng các peer đã ghi trong file đó (phải cùng `NET_SEED` và `CHURN_STEPS`)
  thay vì rút ngẫu nhiên.
- `REFRESH_CACHE=<file>` (đi cùng `JOIN_REFRESH`): bảng định tuyến sau vòng làm mới không phụ thuộc r
  (r chỉ dùng lúc ingest), nên job đầu tiên của một seed ghi k-bucket đã làm mới vào file này và các job
  sau của cùng seed nạp lại, thay vì làm mới lần nữa (bớt khoảng 2 trong 16 phút của một job ở
  N = 10.000). Chỉ nạp khi file khớp commit, `NET_SEED`, số vòng làm mới, tập ID peer và bảng định tuyến
  trước khi làm mới; khác bất kỳ điều nào thì làm mới như thường và ghi đè. File kết quả ghi
  `refresh_cache_loaded` cho biết job đã làm mới thật hay nạp bộ đệm.

`kill_random_nodes` nay trả về tập peer bị tắt (trước trả về số lượng; không nơi nào dùng giá trị này).

## Thiết kế

- **old**: đúng lệnh nhóm `avail` của đợt 1 (code, N = 10.000, 20.000 object, 500 object được đo,
  r = 1, 2, 3, 10 seed, mất 0 đến 50% peer bước 5%), thêm `RECORD_KILLS=1`. Số đo phải trùng file cùng tên
  của đợt 1 (`ppna_r1/out_dot1/avail`).
- **full**: cùng lệnh, thêm `JOIN_REFRESH=1` và `KILL_FROM` = file của job old cùng r, cùng seed. Hai job
  cùng ID peer, cùng ma trận chiếu, cùng object được đo và cùng tập peer chết ở mọi mức; chỉ khác bảng
  định tuyến, và vì vậy khác chỗ đặt record và shard lúc ingest và kết quả lookup lúc đo. Job full cũng ghi
  `killed_hex` để kiểm việc phát lại. Chạy thành hai nhóm nối tiếp: `full_a` (r = 1) làm mới k-bucket và
  ghi bộ đệm mỗi seed (`ppna_r1/out_dot6/refresh_cache/`), `full_b` (r = 2, 3) nạp bộ đệm. Kết quả của cả
  hai nhóm nằm chung trong `ppna_r1/out_dot6/full/`.
- **chk**: job r = 1 của seed đầu chạy lại với bộ đệm, ghi vào `ppna_r1/out_dot6/chk/`. Bước report kiểm
  nó trùng từng số với job full cùng r, cùng seed (làm mới thật). Bước smoke kiểm điều tương tự trên
  mạng 800 peer.

## Chạy

```bash
cd ~/V_ENGRAM_SIMULATION
git checkout ppna-r1-dot6
sha256sum -c ppna_r1/SHA256SUMS_dot6
source venv/bin/activate
bash ppna_r1/run_dot6.sh
```

Khoảng 5 giờ 20 phút trên máy 2 nhân (`PARALLEL=2`): job join cũ khoảng 5 phút, job join đầy đủ có làm
mới k-bucket khoảng 16 phút, job nạp bộ đệm khoảng 14 phút. Bước report so nhóm old với `REF_ROOT` (mặc định
`ppna_r1/out_dot1/avail`, có trên server); không có thì bỏ qua phần hồi quy.

## Kết quả

- `ppna_r1/out_dot6/old/`, `ppna_r1/out_dot6/full/`: một file JSON mỗi job (r, seed), mỗi file có số đo
  ở 11 mức mất peer. `ppna_r1/out_dot6/chk/`: job kiểm bộ đệm.
- `ppna_r1/out_dot6/refresh_cache/`: bộ đệm k-bucket, chỉ là file trung gian (khoảng vài MB mỗi seed), xoá
  được sau khi chạy xong.
- `ppna_r1/dot6_report.txt`, `ppna_r1/dot6_summary.json`: trung bình ± SD qua seed của metadata, payload,
  end-to-end, còn anchor, còn ít nhất 20 shard sống, shard sống mà lookup bỏ sót; hiệu ghép cặp theo seed
  (join đầy đủ trừ join cũ) kèm KTC 95%; cận giải tích P(Binomial(30, 1 − f) ≥ 20); hồi quy với đợt 1;
  kiểm tập peer chết.
