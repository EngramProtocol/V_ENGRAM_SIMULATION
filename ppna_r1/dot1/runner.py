"""Chạy song song danh sách job của đợt 1 (xem jobs.py). Chạy từ gốc repo.

    python3 ppna_r1/dot1/runner.py --jobs ppna_r1/logs_dot1/jobs.jsonl --parallel 7

- Job đã có file kết quả kèm file .ok ghi đúng commit hiện tại thì bỏ qua. Chạy
  lại cùng lệnh sau khi bị ngắt: chỉ các job chưa xong được chạy.
- Job thiếu file dữ liệu thì không chạy, ghi "thiếu dữ liệu" và liệt kê ở cuối.
- Mỗi job một nhân (OMP/OpenBLAS/MKL = 1 luồng), log riêng trong logs_dot1/.
- Job overlay lớn (>= 35.000 peer) chạy tối đa --big-parallel cái cùng lúc, và chỉ
  khởi động khi RAM trống còn ít nhất --min-free-gb.
- Mã thoát 0 khi mọi job xong; 1 nếu còn job lỗi, quá giờ hoặc thiếu dữ liệu.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone


def utc():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def git_head():
    try:
        return subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return 'nogit'


def mem_available_gb():
    try:
        with open('/proc/meminfo') as fh:
            for line in fh:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return float('inf')


def is_done(job, commit):
    ok = job['out'] + '.ok'
    if not (os.path.isfile(job['out']) and os.path.getsize(job['out']) > 0 and os.path.isfile(ok)):
        return False
    with open(ok) as fh:
        return fh.read().strip() == commit


def valid_json(path):
    try:
        with open(path, encoding='utf-8') as fh:
            json.load(fh)
        return True
    except Exception:
        return False


def fmt_h(sec):
    sec = max(0, int(sec))
    return f'{sec // 3600}h{(sec % 3600) // 60:02d}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', required=True)
    ap.add_argument('--parallel', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument('--big-parallel', type=int, default=3)
    ap.add_argument('--min-free-gb', type=float, default=3.0)
    ap.add_argument('--groups', default='', help='chỉ chạy các nhóm này (cách nhau bởi dấu phẩy)')
    ap.add_argument('--log', default='ppna_r1/logs_dot1/run.log')
    ap.add_argument('--logdir', default='ppna_r1/logs_dot1')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    commit = git_head()
    with open(a.jobs, encoding='utf-8') as fh:
        jobs = [json.loads(line) for line in fh if line.strip()]
    if a.groups:
        keep = set(a.groups.split(','))
        jobs = [j for j in jobs if j['group'] in keep]
    os.makedirs(os.path.dirname(a.log) or '.', exist_ok=True)
    logf = open(a.log, 'a', encoding='utf-8')

    def say(msg):
        line = f'{utc()} {msg}'
        print(line, flush=True)
        logf.write(line + '\n')
        logf.flush()

    done = [j for j in jobs if is_done(j, commit)]
    todo = [j for j in jobs if not is_done(j, commit)]
    missing = [j for j in todo if any(not os.path.exists(p) for p in j['needs'])]
    miss_ids = {j['id'] for j in missing}
    todo = [j for j in todo if j['id'] not in miss_ids]
    # ưu tiên trước, trong cùng mức ưu tiên thì job dài trước (giảm đuôi chờ)
    todo.sort(key=lambda j: (j['prio'], -j['est']))
    say(f'commit {commit} | {len(jobs)} job: {len(done)} đã xong, {len(todo)} cần chạy, '
        f'{len(missing)} thiếu dữ liệu | parallel {a.parallel}, big {a.big_parallel}')
    for j in missing:
        lack = [p for p in j['needs'] if not os.path.exists(p)]
        say(f'  thiếu dữ liệu: {j["id"]} ({", ".join(lack[:3])})')
    if a.dry_run or not todo:
        say('không có job nào cần chạy' if not todo else 'dry run, không chạy')
        return 0 if not missing else 1

    base_env = dict(os.environ)
    base_env.update({'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
                     'NUMEXPR_NUM_THREADS': '1', 'PYTHONUNBUFFERED': '1', 'RUN_COMMIT': commit})
    running = {}          # pid -> (job, Popen, t0, logfh)
    results = {'ok': [], 'fail': [], 'timeout': []}
    est_done, real_done = 0.0, 0.0
    total = len(todo)
    queue = list(todo)
    stop = {'flag': False}

    def handle(sig, frame):
        stop['flag'] = True
    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)

    def launch(j):
        os.makedirs(os.path.dirname(j['out']), exist_ok=True)
        lp = os.path.join(a.logdir, j['id'] + '.log')
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        for p in (j['out'], j['out'] + '.ok'):
            if os.path.exists(p):
                os.remove(p)
        fh = open(lp, 'w', encoding='utf-8')
        fh.write(f'# {utc()} commit {commit}\n# env {json.dumps(j["env"], ensure_ascii=False)}\n'
                 f'# cmd {" ".join(j["cmd"])}\n')
        fh.flush()
        env = dict(base_env)
        env.update(j['env'])
        p = subprocess.Popen(j['cmd'], stdout=fh, stderr=subprocess.STDOUT, env=env,
                             start_new_session=True)
        running[p.pid] = (j, p, time.time(), fh)

    def kill(p):
        try:
            os.killpg(p.pid, signal.SIGTERM)
            for _ in range(30):
                if p.poll() is not None:
                    return
                time.sleep(1)
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    while (queue or running) and not stop['flag']:
        # khởi động job mới
        n_big = sum(1 for (j, _, _, _) in running.values() if j['big'])
        i = 0
        while len(running) < a.parallel and i < len(queue):
            j = queue[i]
            if j['big'] and (n_big >= a.big_parallel or mem_available_gb() < a.min_free_gb):
                i += 1
                continue
            queue.pop(i)
            launch(j)
            n_big += j['big']
        # thu job đã xong
        time.sleep(2)
        for pid in list(running):
            j, p, t0, fh = running[pid]
            rc = p.poll()
            dt = time.time() - t0
            if rc is None and dt > j['timeout']:
                kill(p)
                rc = 'quá giờ'
            if rc is None:
                continue
            fh.close()
            del running[pid]
            good = rc == 0 and valid_json(j['out'])
            if good:
                with open(j['out'] + '.ok', 'w') as okf:
                    okf.write(commit + '\n')
                results['ok'].append(j['id'])
                est_done += j['est']
                real_done += dt
            elif rc == 'quá giờ':
                results['timeout'].append(j['id'])
            else:
                results['fail'].append(j['id'])
            n_fin = sum(len(v) for v in results.values())
            ratio = real_done / est_done if est_done > 0 else 1.0
            rest = sum(x['est'] for x in queue) + sum(
                max(0.0, x['est'] * ratio - (time.time() - t)) / ratio
                for (x, _, t, _) in running.values())
            eta = rest * ratio / max(1, a.parallel)
            tag = 'mã thoát 0' if good else (f'LỖI ({rc})' if rc != 'quá giờ' else 'QUÁ GIỜ')
            say(f'[{n_fin}/{total}] {j["id"]} {tag}, {dt:.0f} giây | còn {len(queue) + len(running)} '
                f'job, ước {fmt_h(eta)}')
            if not good:
                say(f'    xem {os.path.join(a.logdir, j["id"] + ".log")}')
        # không job nào chạy được vì đang chờ RAM: đừng kẹt vòng lặp
        if not running and queue and all(j['big'] for j in queue) and mem_available_gb() < a.min_free_gb:
            say(f'RAM trống {mem_available_gb():.1f} GB < {a.min_free_gb} GB, chờ 60 giây')
            time.sleep(60)

    if stop['flag']:
        say('nhận tín hiệu dừng, kết thúc các job đang chạy')
        for (j, p, _, fh) in list(running.values()):
            kill(p)
            fh.close()
        return 130

    say(f'KẾT THÚC: {len(results["ok"])} xong, {len(results["fail"])} lỗi, '
        f'{len(results["timeout"])} quá giờ, {len(missing)} thiếu dữ liệu')
    for k in ('fail', 'timeout'):
        for x in results[k]:
            say(f'  {k}: {x}')
    return 0 if not (results['fail'] or results['timeout'] or missing) else 1


if __name__ == '__main__':
    sys.exit(main())
