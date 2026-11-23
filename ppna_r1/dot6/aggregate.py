"""Tổng hợp đợt 6: availability của Bảng 9 với join cũ và join đầy đủ trên cùng tập peer chết.

    python3 ppna_r1/dot6/aggregate.py [--root ppna_r1/out_dot6] [--ref ppna_r1/out_dot1/avail]
        [--out ppna_r1/dot6_summary.json] > ppna_r1/dot6_report.txt

- Hồi quy: mọi số đo của nhóm old phải trùng file cùng tên của đợt 1 (--ref), nếu có.
- Kiểm: job full dùng đúng tập peer chết của job old (cùng ID peer bị tắt ở mọi mức), đúng commit;
  job chk (nạp k-bucket từ bộ đệm) trùng từng số với job full cùng r, cùng seed (làm mới thật).
- Bảng: trung bình ± SD qua seed của metadata, payload, end-to-end, còn anchor, còn đủ shard sống,
  shard sống mà lookup bỏ sót; hiệu ghép cặp theo seed (đầy đủ trừ cũ) kèm KTC 95% (t, n - 1 bậc
  tự do); cận giải tích P(Binomial(30, 1 - f) >= 20).
"""
import argparse
import glob
import json
import math
import os
import statistics as st

T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262,
        10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 19: 2.093, 29: 2.045}
KEYS = ['metadata', 'payload', 'e2e', 'metadata_physical', 'payload_physical', 'payload_lookup_miss',
        'mean_alive_shards']
LABEL = {'metadata': 'Metadata', 'payload': 'Payload', 'e2e': 'End-to-end',
         'metadata_physical': 'Còn anchor', 'payload_physical': 'Còn >= 20 shard',
         'payload_lookup_miss': 'Lookup bỏ sót', 'mean_alive_shards': 'Shard sống TB'}


def bound(f, n=30, k=20):
    p = 1 - f
    return 100 * sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def ci(xs):
    n = len(xs)
    m = st.mean(xs)
    if n < 2:
        return m, m, m
    h = T975.get(n - 1, 1.96) * st.stdev(xs) / math.sqrt(n)
    return m, m - h, m + h


def load(root):
    out = {}
    for f in sorted(glob.glob(os.path.join(root, 'kbucket_r*_s*.json'))):
        name = os.path.basename(f)[:-5]
        r = int(name.split('_r')[1].split('_')[0])
        seed = int(name.split('_s')[-1])
        with open(f, encoding='utf-8') as fh:
            out[(r, seed)] = json.load(fh)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='ppna_r1/out_dot6')
    ap.add_argument('--ref', default='ppna_r1/out_dot1/avail')
    ap.add_argument('--out', default='ppna_r1/dot6_summary.json')
    a = ap.parse_args()
    old, full = load(os.path.join(a.root, 'old')), load(os.path.join(a.root, 'full'))
    print('ĐỢT 6: availability (Bảng 9) với join cũ và join đầy đủ, cùng tập peer chết')
    print(f'nhóm old: {len(old)} file | nhóm full: {len(full)} file | root {a.root}')
    problems = []

    # ---- hồi quy với đợt 1
    ref = load(a.ref) if os.path.isdir(a.ref) else {}
    if ref:
        same = 0
        for key, d in old.items():
            if key not in ref:
                problems.append(f'không có file đợt 1 cho r={key[0]} seed={key[1]}')
                continue
            ok = ref[key]['rows'] == d['rows'] and ref[key]['contacts_mean'] == d['contacts_mean']
            same += ok
            if not ok:
                problems.append(f'nhóm old khác đợt 1: r={key[0]} seed={key[1]}')
        print(f'hồi quy: {same}/{len(old)} job join cũ trùng từng số với đợt 1 ({a.ref})')
    else:
        print(f'hồi quy: không có {a.ref}, bỏ qua')

    # ---- tập peer chết và commit
    commits = sorted({d.get('commit', '') for d in list(old.values()) + list(full.values())})
    print(f'commit: {", ".join(commits)}')
    paired = sorted(set(old) & set(full))
    for key in paired:
        o, f = old[key], full[key]
        if f.get('kills_from', '').split('/')[-1] != f'kbucket_r{key[0]}_s{key[1]}.json':
            problems.append(f'job full không phát lại đúng file: {key}')
        if not o.get('killed_hex') or o.get('killed_hex') != f.get('killed_hex'):
            problems.append(f'tập peer chết của job full khác job old: {key}')
    for key in sorted(set(old) ^ set(full)):
        problems.append(f'thiếu cặp old/full: r={key[0]} seed={key[1]}')

    # ---- bộ đệm k-bucket đã làm mới: job nào làm mới thật, job nào nạp; job chk phải trùng từng số
    n_load = sum(1 for d in full.values() if d.get('refresh_cache_loaded') is True)
    n_fresh = sum(1 for d in full.values() if d.get('refresh_cache_loaded') is False)
    print(f'join đầy đủ: {n_fresh} job làm mới k-bucket, {n_load} job nạp từ bộ đệm')
    chk = load(os.path.join(a.root, 'chk'))
    chk_ok = None
    for key, c in chk.items():
        f = full.get(key)
        strip = lambda d: {k: v for k, v in d.items() if k != 'refresh_cache_loaded'}
        chk_ok = (f is not None and c.get('refresh_cache_loaded') is True
                  and f.get('refresh_cache_loaded') is False and strip(c) == strip(f))
        print(f'kiểm bộ đệm (r={key[0]} seed={key[1]}): nạp bộ đệm '
              + ('trùng từng số với làm mới thật' if chk_ok else 'KHÁC làm mới thật'))
        if not chk_ok:
            problems.append(f'job chk khác job full làm mới thật: r={key[0]} seed={key[1]}')
    if not chk and n_load:
        problems.append('có job nạp bộ đệm nhưng không có job chk')

    rs = sorted({k[0] for k in paired})
    steps = old[paired[0]]['churn_steps'] if paired else []
    summary = {'n_pairs': len(paired), 'commits': commits, 'steps': steps, 'by_r': {},
               'refresh_fresh': n_fresh, 'refresh_loaded': n_load, 'cache_check_ok': chk_ok}
    cont_o = [old[k]['contacts_mean'] for k in paired]
    cont_f = [full[k]['contacts_mean'] for k in paired]
    lk = [full[k]['join_refresh'][0]['lookups'] / full[k]['nodes'] for k in paired if full[k].get('join_refresh')]
    print(f'contact mỗi peer: join cũ {st.mean(cont_o):.1f}, join đầy đủ {st.mean(cont_f):.1f}; '
          f'lookup làm mới mỗi peer {st.mean(lk):.2f}' if paired else '')

    for r in rs:
        keys = [k for k in paired if k[0] == r]
        seeds = [k[1] for k in keys]
        print(f'\n=== r = {r} ({len(keys)} seed: {",".join(map(str, seeds))}) ===')
        print(f'{"mất":>5s} {"cận":>6s} | ' + ' | '.join(f'{LABEL[k]:>22s}' for k in KEYS[:6]))
        rows_r = []
        for i, f in enumerate(steps):
            line = f'{f:>5.0%} {bound(f):>6.1f} | '
            cells = []
            row = {'loss': f, 'bound': bound(f)}
            for k in KEYS:
                vo = [old[kk]['rows'][i][k] for kk in keys]
                vf = [full[kk]['rows'][i][k] for kk in keys]
                d = [b - c for b, c in zip(vf, vo)]
                m, lo, hi = ci(d)
                row[k] = {'old_mean': st.mean(vo), 'old_sd': st.stdev(vo) if len(vo) > 1 else 0.0,
                          'full_mean': st.mean(vf), 'full_sd': st.stdev(vf) if len(vf) > 1 else 0.0,
                          'diff_mean': m, 'diff_lo': lo, 'diff_hi': hi,
                          'diff_pos': sum(x > 0 for x in d), 'diff_neg': sum(x < 0 for x in d)}
                if k in KEYS[:6]:
                    cells.append(f'{st.mean(vo):5.1f} -> {st.mean(vf):5.1f} ({m:+5.1f})')
            print(line + ' | '.join(f'{c:>22s}' for c in cells))
            rows_r.append(row)
        summary['by_r'][str(r)] = rows_r
        i30 = [i for i, f in enumerate(steps) if abs(f - 0.30) < 1e-9]
        if i30:
            row = rows_r[i30[0]]
            print('  mất 30%, hiệu ghép cặp (đầy đủ trừ cũ) [KTC 95%], số seed tăng / giảm:')
            for k in ('metadata', 'payload', 'payload_physical', 'payload_lookup_miss', 'e2e'):
                x = row[k]
                print(f'    {LABEL[k]:>16s}: cũ {x["old_mean"]:5.1f} ± {x["old_sd"]:.1f}, đầy đủ '
                      f'{x["full_mean"]:5.1f} ± {x["full_sd"]:.1f}, hiệu {x["diff_mean"]:+.2f} '
                      f'[{x["diff_lo"]:+.2f}; {x["diff_hi"]:+.2f}], {x["diff_pos"]}/{x["diff_neg"]}')

    print('\nVẤN ĐỀ: ' + ('không có' if not problems else f'{len(problems)}'))
    for p in problems:
        print('  - ' + p)
    summary['problems'] = problems
    with open(a.out, 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
    print(f'-> {a.out}')
    return 0 if not problems else 1


if __name__ == '__main__':
    raise SystemExit(main())
