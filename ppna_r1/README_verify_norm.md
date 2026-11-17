# Kiểm chuẩn hoá cột chiếu (tag `ppna-r1-verify-norm`)

## Mục đích

Trả lời hai câu hỏi trước khi sửa bài cho PPNA:

1. Các file kết quả mô hình lý tưởng mà bài dùng có được sinh trước commit chuẩn hoá cột chiếu `d48ec0b` hay không. Server nhận commit này lúc 2026-08-17 13:45:32 UTC (merge `3fbb0c6`).
2. Nếu có, chuẩn hoá làm đổi số bao nhiêu.

Chuẩn hoá không đổi dấu của phép chiếu, nên khoá gốc và vị trí record giữ nguyên. Nó chỉ đổi thứ tự margin, tức bit nào được lật khi T > 1. Vì vậy:
- Chạy lại với `NORMALIZE_ROWS=0` phải trùng từng số với file cũ, nếu file cũ đúng là bản chưa chuẩn hoá.
- Hiệu `NORMALIZE_ROWS=1` trừ `NORMALIZE_ROWS=0` là tác động thật của chuẩn hoá.
- Đối chứng T = 1 (không lật bit nào) phải trùng nhau ở cả hai chế độ.

Đợt này không sửa code mô phỏng; chỉ thêm thư mục `ppna_r1/`. File cũ trên server không bị ghi đè; kết quả mới nằm trong `ppna_r1/out_verify_norm/`.

**Khối lượng:** 46 job = 2 corpus × 2 chế độ × 10 seed, cộng 6 job đối chứng. Mỗi job khoảng 1 đến 3 phút; với `PARALLEL=4` mất khoảng 20 đến 40 phút.

## Trên laptop

```bash
cd V_ENGRAM_SIMULATION
git checkout main && git pull
git log --oneline -1                     # phải là: b99bd9d README: cite tag instead of commit hash
git am ~/Downloads/0001-ppna-r1-verify-norm*.patch
sha256sum -c ppna_r1/SHA256SUMS_verify_norm     # 5 dòng OK (máy Mac: shasum -a 256 -c ...)
git tag -a ppna-r1-verify-norm -m "ppna r1: kiem chuan hoa cot chieu"
git push origin main --tags
```

## Trên server

```bash
cd ~/V_ENGRAM_SIMULATION
git status --short | grep -v '^??'      # không in gì
git fetch origin --tags && git checkout ppna-r1-verify-norm
git describe --tags                      # ppna-r1-verify-norm
sha256sum -c ppna_r1/SHA256SUMS_verify_norm
[ -f venv/bin/activate ] && source venv/bin/activate
tmux new -s verifynorm -d "PARALLEL=4 bash ~/V_ENGRAM_SIMULATION/ppna_r1/run_verify_norm.sh"
```

**Kiểm sau khoảng 5 phút:**

```bash
cat ppna_r1/logs_verify_norm/env.txt     # "d48ec0b nằm trong HEAD: có", mục file đã track bị sửa phải trống
tail -3 ppna_r1/logs_verify_norm/run.log
```

**Khi xong** (dòng cuối `run.log` là `XONG KIỂM CHUẨN HOÁ`):

```bash
grep -c "mã thoát" ppna_r1/logs_verify_norm/run.log       # 46
grep "mã thoát [1-9]" ppna_r1/logs_verify_norm/run.log    # không in gì
tar czf ~/vengram_verify_norm.tar.gz ppna_r1/out_verify_norm ppna_r1/logs_verify_norm ppna_r1/verify_norm_report.txt
tar tzf ~/vengram_verify_norm.tar.gz | grep -c json        # 46
sha256sum ~/vengram_verify_norm.tar.gz
```

Lấy file về laptop bằng `scp` như mọi lần, rồi gửi file tar.gz.

Nếu tmux bị ngắt, chạy lại với `SKIP_DONE=1` đặt trước `bash` trong lệnh tmux; các job đã xong sẽ được bỏ qua.

## Cách đọc `verify_norm_report.txt`

- **Phần 1:** liệt kê mọi cấu hình mô hình lý tưởng trên đĩa, mỗi cấu hình được gắn một nhãn:
  - **TRƯỚC:** mọi seed được ghi trước mốc.
  - **SAU:** mọi seed được ghi sau mốc.
  - **TRỘN:** có cả seed trước và seed sau mốc.
- **Phần 2:** so cấu hình chính (CodeSearchNet và SciFact, 10 seed). Có ba kết luận khả dĩ:
  - **XÁC NHẬN:** file cũ trùng từng số với bản không chuẩn hoá, tức file cũ là bản cũ.
  - **BÁC BỎ:** file cũ trùng bản có chuẩn hoá, tức nghi vấn sai cho cấu hình này.
  - **CHƯA RÕ:** file cũ không trùng bản nào; có khác biệt khác ngoài chuẩn hoá.

  Dòng "tác động chuẩn hoá" cho biết mức thay đổi trung bình, khoảng tin cậy 95% và mức lệch lớn nhất ở một seed.
- **Phần 3:** đối chứng T = 1 phải "KHỚP"; nếu "LỆCH" thì phép so A/B không sạch.

Đợt này không kiểm Bảng 6 (Bucket-LSH, sinh bằng `baselines.py`) và các file iterative `result_full_*`.
