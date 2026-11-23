#!/bin/bash
# =============================================================================
# ĐỢT 6 (ppna-r1-dot6): availability của Bảng 9 trên overlay k-bucket với join đầy đủ, ghép cặp với
# join cũ trên đúng cùng tập peer chết. Hướng dẫn: ppna_r1/README_dot6.md
#
#   bash ppna_r1/run_dot6.sh
#
# Bốn bước (STAGES, mặc định cả bốn):
#   smoke   mạng 800 peer: join cũ, join đầy đủ phát lại tập peer chết, rồi join đầy đủ nạp k-bucket
#           từ bộ đệm (phải trùng từng số với lần làm mới thật); dưới 1 phút
#   old     30 job: đúng lệnh nhóm avail của đợt 1 (join cũ, r = 1, 2, 3, 10 seed, mất 0..50%), có ghi
#           ID peer bị tắt; số đo phải trùng đợt 1
#   full    30 job cùng lệnh với join đầy đủ, tắt đúng các peer mà job old cùng r, cùng seed đã tắt:
#           trước là full_a (r = 1, làm mới k-bucket và ghi bộ đệm mỗi seed), sau là chk (r = 1 của
#           seed đầu nạp bộ đệm, để kiểm) và full_b (r = 2, 3, nạp bộ đệm)
#   report  ppna_r1/dot6_report.txt và ppna_r1/dot6_summary.json; hồi quy với REF_ROOT nếu có
# Tuỳ chọn: PARALLEL (mặc định nproc - 1), PY, REF_ROOT (ppna_r1/out_dot1/avail), SEEDS (mặc định 10 seed).
# Chạy lại đúng lệnh sau khi bị ngắt: job đã xong với cùng commit được bỏ qua.
# =============================================================================
set -u
cd "$(dirname "$0")/.." || exit 1
LOG=ppna_r1/logs_dot6
mkdir -p "$LOG/smoke"
if [ -z "${PY:-}" ]; then
    if [ -x venv/bin/python ]; then PY=venv/bin/python; else PY=python3; fi
fi
export PY
STAGES="${STAGES:-smoke old full report}"
NP=$(nproc)
PARALLEL="${PARALLEL:-$(( NP > 1 ? NP - 1 : 1 ))}"
REF_ROOT="${REF_ROOT:-ppna_r1/out_dot1/avail}"

if ! "$PY" -c "import numpy, simpy" 2>/dev/null; then
    echo "Thiếu numpy hoặc simpy trong $PY. Chạy: source venv/bin/activate"
    exit 1
fi
DIRTY=$(git status --short | grep -v '^??')
if [ -n "$DIRTY" ] && [ "${ALLOW_DIRTY:-0}" != "1" ]; then
    echo "Có file đã track bị sửa; mọi kết quả phải sinh từ đúng commit của tag. Dừng."
    echo "$DIRTY"
    exit 1
fi
{
    echo "HEAD = $(git rev-parse --short HEAD) | tag = $(git describe --tags --exact-match 2>/dev/null || echo '-')"
    echo "nproc = $NP | PARALLEL = $PARALLEL | STAGES = $STAGES | REF_ROOT = $REF_ROOT | SEEDS = ${SEEDS:-mặc định}"
    free -g | head -2
    "$PY" -c "import sys, numpy, simpy; print('python', sys.version.split()[0], '| numpy', numpy.__version__, '| simpy', simpy.__version__)"
} > "$LOG/env.txt" 2>&1
cat "$LOG/env.txt"

run_group() {   # $1 tên file job, $2 các nhóm
    "$PY" ppna_r1/dot6/jobs.py --groups "$2" --write "$LOG/jobs_$1.jsonl"
    "$PY" ppna_r1/dot1/runner.py --jobs "$LOG/jobs_$1.jsonl" --parallel "$PARALLEL" \
        --log "$LOG/run.log" --logdir "$LOG"
}

for st in $STAGES; do
    echo "$(date -u +%FT%TZ) == $st ==" | tee -a "$LOG/run.log"
    case $st in
    smoke)
        # smoke luôn chạy lại từ đầu, kể cả bộ đệm, để lần làm mới thật không bị thay bằng bộ đệm cũ
        rm -rf ppna_r1/out_dot6/sm_old ppna_r1/out_dot6/sm_full ppna_r1/out_dot6/sm_full_c \
            ppna_r1/out_dot6/sm_cache
        "$PY" ppna_r1/dot6/jobs.py --groups sm --write "$LOG/smoke/jobs.jsonl" > /dev/null
        rc=0
        for g in sm_old sm_full sm_full_c; do
            "$PY" ppna_r1/dot1/runner.py --jobs "$LOG/smoke/jobs.jsonl" --groups "$g" --parallel 1 \
                --log "$LOG/smoke/run.log" --logdir "$LOG/smoke" || rc=1
        done
        "$PY" - <<'PYEOF' || rc=1
import glob, json
o = json.load(open(glob.glob('ppna_r1/out_dot6/sm_old/*.json')[0]))
f = json.load(open(glob.glob('ppna_r1/out_dot6/sm_full/*.json')[0]))
c = json.load(open(glob.glob('ppna_r1/out_dot6/sm_full_c/*.json')[0]))
assert o['killed_hex'] == f['killed_hex'], 'tập peer chết khác nhau'
assert f['contacts_mean'] > o['contacts_mean'], 'join đầy đủ không thêm contact'
assert f['refresh_cache_loaded'] is False and c['refresh_cache_loaded'] is True, 'bộ đệm không dùng đúng'
strip = lambda d: {k: v for k, v in d.items() if k != 'refresh_cache_loaded'}
assert strip(f) == strip(c), 'nạp bộ đệm cho kết quả khác làm mới thật'
print(f"smoke: cùng tập peer chết; contact {o['contacts_mean']:.1f} -> {f['contacts_mean']:.1f}; "
      f"nạp bộ đệm trùng từng số với làm mới thật")
PYEOF
        if [ $rc -ne 0 ]; then echo "SMOKE TEST LỖI, dừng." | tee -a "$LOG/run.log"; exit 1; fi
        ;;
    old)
        run_group old old
        rc=$?
        if [ $rc -ne 0 ]; then echo "Nhóm old lỗi (mã $rc), dừng." | tee -a "$LOG/run.log"; exit 1; fi
        ;;
    full)
        run_group full_a full_a
        rc=$?
        if [ $rc -ne 0 ]; then echo "Nhóm full_a lỗi (mã $rc), dừng." | tee -a "$LOG/run.log"; exit 1; fi
        run_group full_b chk,full_b
        rc=$?
        if [ $rc -ne 0 ]; then echo "Nhóm full_b lỗi (mã $rc), dừng." | tee -a "$LOG/run.log"; exit 1; fi
        ;;
    report)
        "$PY" ppna_r1/dot6/aggregate.py --root ppna_r1/out_dot6 --ref "$REF_ROOT" \
            --out ppna_r1/dot6_summary.json > ppna_r1/dot6_report.txt 2>&1
        rc=$?
        echo "$(date -u +%FT%TZ) report mã thoát $rc: ppna_r1/dot6_report.txt" | tee -a "$LOG/run.log"
        cat ppna_r1/dot6_report.txt
        ;;
    *) echo "Không biết bước '$st'"; exit 1 ;;
    esac
done
echo "XONG ĐỢT 6" | tee -a "$LOG/run.log"
