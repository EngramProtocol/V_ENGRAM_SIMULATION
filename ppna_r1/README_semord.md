# Semord: so sánh với artifact của tác giả (tag `ppna-r1-semord4`; điểm vận hành L = 8: `ppna-r1-semord5`)

## Mục đích

R1-5 hỏi về baseline vector search phi tập trung gần đây. Semord (Wang và cộng sự, arXiv
2609.25514, 9/2026) là hệ gần nhất về bài toán: overlay phi tập trung, mỗi query liên lạc một số ít
peer. Semord khác V-Engram ở cả cách đặt khoá (VHash, hàm băm học từ dữ liệu) lẫn overlay (VecDHT,
vòng kiểu Chord có thư mục vùng), nên được báo như một điểm tham chiếu ngoài, chạy bằng chính code
của tác giả:

- LearnedHash, commit `542528c8` (VHash: chọn cấu hình, huấn luyện, sinh code).
- Vortex_system, commit `8766ddb5` (VecDHT, simulator OverlaySim, benchmark `vortex_bench`).

Sửa duy nhất là `semord/learnedhash_linux.patch`: trên Linux `uint64_t` là `unsigned long` nên
literal `0ULL` gọi constructor `ModelInput` bị mơ hồ (tác giả build trên macOS). Không đổi logic.

## Thiết lập

- **Quy mô.** Simulator của artifact dựng underlay full mesh, bộ nhớ tăng theo N²: 0,35 GB ở 500
  node, 0,79 GB ở 1.000, 2,4 GB ở 2.000 (ước khoảng 50 GB ở 10.000). Vì vậy phép so đặt ở
  N = 1.000 peer, mức lớn nhất trong dải tác giả đánh giá (32 đến 1.024 node).
- **V-Engram** ở cùng N: mô hình iterative với join đầy đủ, T = 8, L = 5, K = 2 (= N/500, cùng tỉ
  lệ N/K với cấu hình chính nên cùng độ dài tiền tố hiệu dụng), thêm K = 4 và 10.
- **Semord.** Cấu hình VHash chọn bằng `vortex_model_selector` của tác giả (vai trò `best`), chạy
  trên 500 query validation, cho overlay 1.000 node; mỗi seed huấn luyện lại model với cấu hình đó.
  Bộ chọn chấm điểm có cả độ trễ và thời gian huấn luyện đo được, nên chạy lại có thể chọn cấu hình
  khác (năm lần chạy bộ chọn cho SciFact, cùng dữ liệu và seed, ra bốn cấu hình). Vì vậy cấu hình
  dùng trong báo cáo được cố định trong `semord/sel/` và pipeline dùng lại; `SEMORD_RESELECT=1` để
  chạy lại bộ chọn. Với cấu hình cố định, phần còn lại xác định: dựng HNSW, huấn luyện model và
  benchmark lặp lại cho cùng kết quả. Ngân sách là `max_query_nodes` (B): 16 (mặc định trong bài
  Semord), 49 (bằng số peer V-Engram liên lạc với K = 2) và 225 (khoảng bằng số ứng viên V-Engram
  xét). Tham số lập kế hoạch truy vấn (vòng ring quanh owner, số vùng, số peer mỗi vùng) chọn trên
  query validation cho từng B trong 4 đến 8 tổ hợp, gồm cả kế hoạch tra trọn từng vùng; báo cả tham
  số mặc định của artifact.
- Cùng corpus, cùng 500 query test, cùng ground truth và Recall@5 như mọi bảng khác; 10 seed.
- Mọi bước chạy một luồng (OMP_NUM_THREADS=1): dựng HNSW nhiều luồng cho đồ thị khác nhau giữa các
  lần chạy, nên skeleton và model VHash cũng khác. Máy khác thư viện BLAS vẫn có thể cho model hơi
  khác.

## Cần trên server

Có sẵn git, make, g++ có C++20 (GCC 10 trở lên), venv của repo (python có pip), truy cập GitHub
và PyPI; khoảng 3 GB đĩa cho code và build. Không cần sudo cho phần còn lại:

- Không có cmake từ 3.16 thì `setup_semord.sh` cài cmake bằng pip vào `$SEMORD_ROOT/tools/cmake`.
- Không có BLAS hoặc LAPACK của hệ thống thì `setup_semord.sh` build OpenBLAS 0.3.26 (có LAPACK
  dịch sang C, không cần Fortran) vào `$SEMORD_ROOT/openblas`, thêm khoảng 5 đến 10 phút. Lần chạy
  thử dùng BLAS và LAPACK tham chiếu của netlib, nên model VHash trên server có thể hơi khác.

Query validation (`data/*_val_query_embeddings.npy`) đã có từ bước chuẩn bị của đợt 1.

## Chạy

```bash
cd ~/V_ENGRAM_SIMULATION
git fetch origin --tags && git checkout ppna-r1-semord4
sha256sum -c ppna_r1/SHA256SUMS_semord
source venv/bin/activate
tmux new -s semord -d "bash ~/V_ENGRAM_SIMULATION/ppna_r1/run_semord.sh"
```

Theo dõi và khi xong:

```bash
tail -3 ppna_r1/logs_semord/run.log
grep -c "XONG SEMORD" ppna_r1/logs_semord/run.log      # 1 là xong
tmux ls                     # không còn phiên semord mà grep ra 0 là có bước lỗi
cat ppna_r1/semord_report.txt
tar czf ~/vengram_semord.tar.gz ppna_r1/out_semord ppna_r1/logs_semord ppna_r1/semord_report.txt ppna_r1/semord_summary.json
sha256sum ~/vengram_semord.tar.gz
```

Bước `setup` chỉ dừng vì công cụ khi thiếu git, make, python3 hoặc g++ từ bản 10, là những thứ cần
sudo để cài; khi đó script in lệnh cài. Chạy lại đúng lệnh tmux sau khi cài; các bước đã xong được
giữ (OpenBLAS, build, job V-Engram). Model VHash và từng lần chạy Semord chỉ được dùng lại khi đúng
cấu hình VHash hiện tại (ghi trong `semord_config.json` của model và `vhash_config` của kết quả),
nên chạy lại sau một lần chạy dở với cấu hình khác thì phần đó tự huấn luyện và chạy lại.

**Thời gian ước trên server (8 nhân):** setup 10 đến 20 phút (biên dịch; thêm 5 đến 10 phút nếu
phải build OpenBLAS), artifact khoảng 20 phút (một luồng: chọn cấu hình, huấn luyện 20 model, build
benchmark), V-Engram 20 job khoảng 15 phút, Semord validation 38 lần chạy và test 100 lần chạy
khoảng 20 phút với 7 tiến trình (mỗi tiến trình khoảng 0,8 GB RAM). Tổng khoảng 1 giờ đến 1 giờ 30.

## Điểm 2.000 peer

Điểm quy mô thứ hai, để thấy xu hướng khi N tăng (simulator của artifact không chạy được ở 10.000
peer). Chạy sau `run_semord.sh`, dùng lại setup, dữ liệu và build:

```bash
bash ppna_r1/run_semord_n2000.sh
```

- **Semord.** Cấu hình VHash cho overlay 2.000 node chọn bằng bộ chọn của tác giả trên query
  validation (`--node-count-values 2000`), chạy một lần rồi cố định trong
  `semord/sel/<ds>_sel_n2000.json`; model huấn luyện riêng, tên `vortex_v1_<ds>_n2000_s<seed>`.
  Ngân sách B = 53 và B = 97, bằng số peer V-Engram liên lạc với K = 2 và K = 4 ở 2.000 peer (trung
  bình 10 seed: 52,7 và 97,2, tức 2,6% và 4,9% mạng); kế hoạch truy vấn chọn trên validation cho
  từng B, kèm kế hoạch mặc định ở B = 53.
- **V-Engram.** K = 4 (= N/500, cùng tỉ lệ N/K với cấu hình chính), thêm K = 2 (cùng số peer liên
  lạc tuyệt đối như K = 2 ở 1.000 peer) và K = 10.
- Mỗi tiến trình Semord ở 2.000 node cần khoảng 2,4 GB RAM.
- Kết quả: `out_semord/runs_n2000`, `out_semord/vk2000`, `out_semord/sel_n2000`,
  `semord_report_n2000.txt`, `semord_summary_n2000.json`.

## Điểm vận hành L = 8 (tag `ppna-r1-semord5`)

Phép so ở trên đặt V-Engram ở cấu hình chính (L = 5, T = 8). Bước này thêm V-Engram ở điểm vận hành
L = 8, T = 5 của mục chọn điểm vận hành (chọn ở đợt 1, trước phép so với Semord): cùng 40 lookup mỗi
query như cấu hình chính, nhưng 8 record mỗi object thay vì 5. Semord chạy ở đúng ngân sách tương ứng.

- **V-Engram.** Kế hoạch `lt` của `dot2/iterative.py` (biến thể L8_T5 và L8_T8 trên cùng một mạng),
  K = N/500, join đầy đủ, code và SciFact, 10 seed, ở N = 1.000 và 2.000.
- **Ngân sách của Semord.** B bằng số peer V-Engram L8_T5 liên lạc, trung bình 10 seed trên hai
  corpus, làm tròn (`out_semord/budget_l8_n<N>.json`), cùng cách đặt B = 49, 53 và 97.
- **Semord.** Cùng model VHash (cấu hình cố định trong `semord/sel/`); kế hoạch truy vấn chọn trên
  query validation ở ngân sách B (gộp vào `val_best.json`); test 10 seed, kèm kế hoạch mặc định khi
  B ≤ 64, như các ngân sách khác.

```bash
bash ppna_r1/run_semord_l8.sh
```

Chạy sau `run_semord.sh` và `run_semord_n2000.sh`, vì cần build, dữ liệu, model VHash và
`val_best.json` của hai script đó. Kết quả: `out_semord/vk1000_L8`, `out_semord/vk2000_L8`, các lần
chạy Semord mới trong `out_semord/runs` và `out_semord/runs_n2000`, `semord_report_l8_n1000.txt`,
`semord_report_l8_n2000.txt` và hai file `semord_summary_l8_n*.json`. Thời gian ước trên máy 2 nhân:
khoảng 1 giờ ở 1.000 peer và 1 giờ 30 ở 2.000 peer.

Thay đổi code đi kèm, không đổi kết quả nào đã có: kế hoạch `lt` lấy K từ `--k` (mặc định 20 như
đợt 4); `run_semord.py` gộp lựa chọn mới vào `val_best.json` thay vì ghi đè; `aggregate_semord.py`
nhận nhiều thư mục V-Engram và biến thể ghép cặp `--ref-var`.

## Kết quả đã có

Số của bài lấy từ lần chạy bằng chính release này trên máy thử (2 nhân, BLAS và LAPACK tham chiếu
của netlib), ở cả 1.000 và 2.000 peer; phân tích nằm trong `claude/Bao_cao_V_Engram_PPNA_Semord.md`
của Project. Chạy lại toàn bộ từ đầu ở 1.000 peer cho cùng mọi số, trừ các số đo thời gian. Model
VHash phụ thuộc nhẹ vào thư viện BLAS: với OpenBLAS 0.3.26 tự build, hai seed thử ở B = 49 lệch 0,00
đến 0,04 điểm R@5 trên SciFact và tới 0,76 điểm trên code ở từng seed.
