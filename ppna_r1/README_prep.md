# Chuẩn bị dữ liệu cho đợt 1 (tag `ppna-r1-prep`)

## Mục đích

Dựng các bộ dữ liệu mới mà đợt 1 cần, chạy hết trên server, không dùng Colab.

| Bước | Ra file trong `data/` | Dùng cho | Thời gian ước |
|---|---|---|---|
| p1 | `{code,scifact}_val_query_embeddings.npy`, `{code,scifact}_val_ground_truth.json`: 500 query validation mỗi corpus | R1-5, chọn độ rộng Bucket-LSH trên tập tách khỏi tập đánh giá | 10 đến 20 phút (phần lớn là tải parquet CodeSearchNet) |
| p3 | `code30k`, `code40k`, `code70k`: corpus trung gian cho 15.000, 20.000 và 35.000 peer | R1-3, weak scaling | 10 đến 20 phút |
| p4 | `{code,scifact}_pq_{codebook,codes}_m64.npy`, `_m128.npy` | R1-1, sweep PQ | khoảng 10 phút |
| e5 | `code_e5`, `scifact_e5`: intfloat/e5-large-v2, 1024 chiều, PQ m = 512 | R1-4 | 1,5 đến 4 giờ trên CPU |
| jina | `code_jina`: jinaai/jina-code-embeddings-0.5b, 896 chiều, PQ m = 448 | R1-4 | 2 đến 5 giờ trên CPU |

Bước smoke chạy trước tất cả (khoảng 15 phút): tải model và dữ liệu, nhúng thử vài chục văn bản, in thời gian ước cho e5 và jina. Smoke lỗi thì script dừng, không tốn giờ máy.

Các điểm cần biết:
- **Query validation.** p1 dựng lại corpus code 20.000 hàm từ parquet CodeSearchNet và kiểm khớp từng văn bản với `data/code_corpus_texts.json`; kiểm 500 query đánh giá trùng câu đầu docstring của hàm nguồn; với SciFact kiểm 500 claim đánh giá có trong bộ claim tải về. Query validation không trùng query đánh giá nào. Trước khi nhúng, p1 nhúng lại các query đánh giá bằng BGE và so với file đã có, để chắc embedding trên server cùng không gian với bản gốc.
- **Model khác.** Corpus và query giữ nguyên văn bản của bộ BGE. e5 dùng tiền tố `query: ` và `passage: ` như Evo-Engram; jina dùng prompt `nl2code` của model. Cả ba model cắt ở 512 token. Ground truth là top-10 chính xác trong không gian của chính model đó.
- **Corpus trung gian.** Cỡ S là S dòng đầu của `code100k`, query là 500 query của bộ code, ground truth và PQ dựng riêng cho từng cỡ. p3 dựng lại `code50k` bằng cùng quy trình và so với bản của notebook trước khi dựng cỡ mới.
- File mới không bị git theo dõi (`.gitignore` đã có `data/*.npy`, `data/*.json`); `data/manifest.json` không bị sửa, thông tin bộ mới ghi vào `data/manifest_r1.json`.
- Embedding được lưu theo khối 1.000 văn bản trong `data/_prep_cache/`. Nếu tmux bị ngắt, chạy lại đúng lệnh: bước đã xong được bỏ qua, bước nhúng dở chạy tiếp từ khối cuối.

## Trên laptop

```bash
cd ~/V_Engram_Simulation
git checkout main && git pull
git log --oneline -1                     # phải là: ppna r1: verify s2, kiem muc 2.1-2.4
git am ~/Downloads/0001-ppna-r1-chuan-bi-du-lieu*.patch
sha256sum -c ppna_r1/SHA256SUMS_prep     # mọi dòng OK
git tag -a ppna-r1-prep -m "ppna r1: chuan bi du lieu dot 1"
git push origin main --tags
```

## Trên server

**1. Lấy code**

```bash
cd ~/V_ENGRAM_SIMULATION
git status --short | grep -v '^??'      # không in gì
git fetch origin --tags && git checkout ppna-r1-prep
sha256sum -c ppna_r1/SHA256SUMS_prep
ls data/code50k_corpus_embeddings.npy data/code100k_corpus_embeddings.npy data/code100k_corpus_texts.json
df -h .                                 # cần trống khoảng 8 GB (model, venv, dữ liệu mới)
```

**2. Tạo môi trường riêng `venv_prep`** (một lần; không đụng `venv` mô phỏng)

```bash
python3 -m venv venv_prep
venv_prep/bin/pip install --upgrade pip
venv_prep/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
venv_prep/bin/pip install -r ppna_r1/requirements_prep.txt
venv_prep/bin/python -c "import torch, sentence_transformers, transformers, faiss; print(torch.__version__, sentence_transformers.__version__, transformers.__version__)"
```

Nếu `nvidia-smi` chạy được trên server thì cài torch bản CUDA thay cho dòng `--index-url .../cpu`; script tự dùng GPU khi có.

**3. Chạy**

```bash
tmux new -s prep -d "bash ~/V_ENGRAM_SIMULATION/ppna_r1/run_prep.sh"
```

Nếu không tải được từ Hugging Face (lỗi kết nối ở bước smoke), chạy lại với mirror:

```bash
tmux new -s prep -d "HF_ENDPOINT=https://hf-mirror.com bash ~/V_ENGRAM_SIMULATION/ppna_r1/run_prep.sh"
```

**Kiểm sau khoảng 20 phút** (smoke đã xong):

```bash
cat ppna_r1/logs_prep/run.log           # các dòng smoke phải có "mã thoát 0", kèm thời gian ước của e5 và jina
cat ppna_r1/logs_prep/env.txt
```

Gửi trước nội dung `run.log` nếu muốn kiểm thời gian ước. **Theo dõi:** `tail -3 ppna_r1/logs_prep/e5.log` hoặc `jina.log` in số văn bản đã nhúng và số phút còn lại. Trong lúc chạy không nên chạy job nặng khác trên server, vì bước nhúng dùng hết số nhân.

**Khi xong** (dòng cuối `run.log` là `XONG CHUẨN BỊ DỮ LIỆU`):

```bash
cat ppna_r1/prep_report.txt             # dòng cuối: "KẾT LUẬN: 0 lỗi"
tar czf ~/vengram_prep.tar.gz ppna_r1/logs_prep ppna_r1/prep_out ppna_r1/prep_report.txt data/manifest_r1.json
sha256sum ~/vengram_prep.tar.gz
```

Gửi file tar.gz (vài trăm KB). Dữ liệu mới nằm lại trong `data/` trên server cho đợt 1.

Chạy riêng một bước: `STAGES="p1 report" bash ppna_r1/run_prep.sh`. Muốn chạy lại một bước đã xong thì xoá file `.ok` của bước đó trong `ppna_r1/logs_prep/`.
