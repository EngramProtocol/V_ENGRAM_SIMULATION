# Đợt 5: Bảng 10 (churn) trên mô hình iterative (tag `ppna-r1-dot5`)

## Mục đích

Bảng 10 (r = 1 không sửa, r = 1 sửa mỗi 480 phút, r = 4 sửa mỗi 1.320 phút) hiện chỉ có số của mô hình
lý tưởng (`main_churn_engine.py`): lookup trả đúng r hoặc K peer XOR-gần nhất trong các peer đang sống,
và peer vừa tham gia được mọi peer biết ngay. Đợt 5 chạy đúng kịch bản churn đó trên giao thức của mô
hình iterative (`ppna_r1/dot5/churn_iter.py`), cùng 10 seed, code, N = 10.000, 200 query, rồi ghép cặp
theo seed với số lý tưởng của đợt 1.

## Mô hình

- **Mạng lúc t = 0**: mạng của các thí nghiệm iterative tĩnh với join đầy đủ (join tuần tự trên k-bucket,
  một vòng làm mới bucket, ingest bằng Ripple Search), dựng bằng chính `ppna_r1/dot2/iterative.py`.
- **Phiên**: cùng phân bố và cùng dòng số ngẫu nhiên với mô hình lý tưởng (Weibull k = 0,5, median 120
  phút, số peer không đổi). Cùng seed thì peer rời mạng ở đúng các khe và đúng các epoch như mô hình lý
  tưởng; cùng warm-up, thời lượng, epoch, TTL (2,2 chu kỳ sửa) và cùng các lần đo (lệch pha trong chu kỳ
  sửa).
- **Peer rời đi** mất record và bảng định tuyến; peer khác vẫn giữ nó trong k-bucket cho tới khi phát hiện.
- **Peer mới** join đầy đủ: liên lạc một peer bootstrap đang sống, tra chính ID mình, ping các peer tìm
  được, làm mới mọi bucket xa hơn láng giềng gần nhất.
- **Bảo trì k-bucket theo Kademlia**: mọi RPC cho bên nhận học bên gửi và bên gửi làm mới bên trả lời;
  bucket đầy thì ping peer lâu nhất chưa thấy, chỉ thay khi peer đó không trả lời; RPC tới peer đã rời
  mạng hết giờ (vẫn tính một RPC) và bên gửi xoá peer đó. Mỗi peer tra chính ID mình mỗi giờ (chu kỳ làm
  mới của Kademlia), lệch pha đều giữa các peer.
- **Sửa chữa lazy** như mô hình lý tưởng: đủ L·r anchor còn giữ record thì gia hạn TTL; thiếu thì neo lại
  cả L khoá bằng lookup Ripple Search (cùng quy tắc với ingest) từ một peer đang sống, STORE tới r peer
  gần nhất còn trả lời.
- **Đường đọc dưới churn**: client gửi yêu cầu tới K peer đầu của kết quả lookup; peer đã rời mạng thì hết
  giờ (tính một RPC) và client gửi tiếp cho ứng viên kế tiếp, tới khi đủ K peer trả lời. Khi mọi peer sống,
  việc này trùng đúng đường đọc của mô hình tĩnh. Mỗi lần đo cũng tính R@5 và meta định tuyến được của
  client không thay peer, trên đúng các lookup đó (độ nhạy, ghép cặp theo query).
- **Đo**: meta vật lý (anchor còn giữ record), meta định tuyến được (lookup Ripple Search tới từng khoá
  của cùng 500 object lấy mẫu như mô hình lý tưởng), R@5 của 200 query chạy đúng đường đọc iterative
  (L = 5, T = 8, K = 20, c = 16, ADC, κ = 30), số bản sống, message sửa chữa (cùng định nghĩa với mô
  hình lý tưởng: gia hạn và STORE). Lúc đo, lookup và RPC không cập nhật k-bucket. Thêm: chi phí RPC mỗi
  query, số RPC hết giờ, tỉ lệ contact đã chết trong bảng định tuyến, chi phí bảo trì overlay, chi phí
  sửa chữa thật (keep-alive, lookup, STORE).

## Kiểm tra

- **Hồi quy t = 0**: mỗi job đo thêm một lần ngay sau ingest. Với r = 1, R@5 từng query của lần đo này
  phải trùng biến thể `base` của iterative tĩnh với join đầy đủ (nhóm `tk_r` của đợt 3) trên 200 query
  đầu. Lookup của `churn_iter.py` khi mọi peer sống cho đúng kết quả của `iterative_find_k_closest_nodes`
  (đã kiểm trên 3.000 lookup ngẫu nhiên và trên seed 1: R@5 74,5, trùng từng query).
- **Cùng churn**: số lượt rời mạng ở mọi lần đo phải trùng file lý tưởng cùng seed.
- **Chạy tiếp**: smoke test dừng một job giữa chừng rồi chạy tiếp từ checkpoint; kết quả phải trùng lần
  chạy liền một mạch.

## Chạy

```bash
cd ~/V_ENGRAM_SIMULATION
git fetch origin --tags && git checkout ppna-r1-dot5
sha256sum -c ppna_r1/SHA256SUMS_dot5
source venv/bin/activate
tmux new -s dot5 -d "bash ~/V_ENGRAM_SIMULATION/ppna_r1/run_dot5.sh"
```

Theo dõi: `tail -3 ppna_r1/logs_dot5/run.log`; xong khi có dòng `XONG ĐỢT 5`. Kết quả:
`ppna_r1/out_dot5/churn_it`, `ppna_r1/dot5_report.txt`, `ppna_r1/dot5_summary.json`. Bước report đọc số lý
tưởng ở `ppna_r1/out_dot1/churn` và số tĩnh ở `ppna_r1/out_dot3/tk_r` (đặt `IDEAL_ROOT`, `STATIC_ROOT` nếu
để chỗ khác).

**Thời gian ước:** khoảng 30 giờ một nhân (job r = 4 dài nhất, khoảng 2 giờ). Job bị ngắt chạy tiếp từ
checkpoint (`<file kết quả>.ckpt`, ghi mỗi 15 phút); chạy lại đúng lệnh trên là đủ.
