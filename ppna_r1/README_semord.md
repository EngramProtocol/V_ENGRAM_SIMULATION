# Semord: so sánh với artifact của tác giả (tag `ppna-r1-semord3`)

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
  query validation cho từng B; báo cả tham số mặc định của artifact.
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
git fetch origin --tags && git checkout ppna-r1-semord3
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
benchmark), V-Engram 20 job khoảng 15 phút, Semord validation 28 lần chạy và test 100 lần chạy
khoảng 20 phút với 7 tiến trình (mỗi tiến trình khoảng 0,8 GB RAM). Tổng khoảng 1 giờ đến 1 giờ 30.

## Kết quả đã có

Lần chạy trên máy thử (cùng script, cùng commit của artifact, cùng cấu hình VHash cố định) và phân
tích nằm trong `claude/Bao_cao_V_Engram_PPNA_Semord.md` của Project. Lần chạy trên server để mọi số
của bài sinh từ cùng một release. Model VHash phụ thuộc nhẹ vào thư viện BLAS: máy thử dùng BLAS
tham chiếu của netlib; với OpenBLAS 0.3.26 tự build, SciFact seed 1, B = 49 cho R@5 69,48 so với
69,52 (kế hoạch truy vấn chọn trên validation) và trùng 35,40 (kế hoạch mặc định).
