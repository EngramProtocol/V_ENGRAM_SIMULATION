#!/usr/bin/env python3
"""Gom kết quả các bước chuẩn bị thành ppna_r1/prep_report.txt."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, OUT  # noqa: E402

lines, n_err, n_warn = [], 0, 0


def say(s=""):
    lines.append(s)


def mark(ok, warn_only=False):
    global n_err, n_warn
    if ok:
        return "OK"
    if warn_only:
        n_warn += 1
        return "CẢNH BÁO"
    n_err += 1
    return "LỖI"


def load(step):
    p = OUT / f"{step}.json"
    return json.load(open(p, encoding="utf-8")) if p.exists() else None


def fmt(x, nd=1):
    return f"{x:.{nd}f}".replace(".", ",")


def num(n):
    return f"{int(n):,}".replace(",", ".")


def main():
    say("BÁO CÁO CHUẨN BỊ DỮ LIỆU ĐỢT 1")
    env = OUT.parent / "logs_prep" / "env.txt"
    if env.exists():
        say(env.read_text(encoding="utf-8").splitlines()[0])
    ref_angle = {}
    mf = DATA / "manifest.json"
    if mf.exists():
        ref_angle = {e["name"]: e["angle_mean"] for e in json.load(open(mf, encoding="utf-8"))}
    say()

    p1 = load("p1_validation")
    say("[p1] Query validation (R1-5)")
    if p1 is None:
        say("  chưa chạy"); mark(False)
    else:
        c = p1["code"]
        built = c["tried"][-1]
        say(f"  code: corpus dựng lại từ {c['parquet_file']}: khớp {num(built['n_match'])}/20.000 văn bản "
            f"... {mark(built['n_match'] == 20000)}")
        say(f"        câu đầu docstring của hàm nguồn khớp query đánh giá: {c['test_text_match']}/500 "
            f"... {mark(c['test_text_match'] == 500)}")
        say(f"        tái lập phép chọn của notebook bằng seed: {'có' if c['notebook_rng_reproduced'] else 'không'} (chỉ để đối chiếu)")
        for name in ("code", "scifact"):
            r = p1[name]
            b = r["bge_recheck"]
            if name == "scifact":
                say(f"  scifact: đọc claim bằng {r['method']}: chứa {r['test_text_match']}/{r['test_unique']} "
                    f"claim đánh giá khác nhau ... {mark(r['test_text_match'] == r['test_unique'])}")
            say(f"        nhúng lại {b['n']} query đánh giá bằng BGE trên server: cos nhỏ nhất {fmt(b['cos_min'], 6)}, "
                f"trung bình {fmt(b['cos_mean'], 6)} ... {mark(b['cos_min'] >= 0.999, warn_only=True)}")
            ov = r["overlap_with_test_text"] + r.get("overlap_with_test_source", 0)
            say(f"        {r['n_val']} query validation, trùng với tập đánh giá: {ov} "
                f"... {mark(r['n_val'] == 500 and ov == 0)}")
            a = r["val_angles"]["angle_mean"]
            say(f"        góc query validation tới GT5: {fmt(a)}° (tập đánh giá: {fmt(ref_angle.get(name, float('nan')))}°)")
    say()

    say("[p2] Model khác (R1-4)")
    for key, names in (("e5", ["code_e5", "scifact_e5"]), ("jina", ["code_jina"])):
        p2 = load(f"p2_{key}")
        if p2 is None:
            say(f"  {key}: chưa chạy"); mark(False); continue
        enc = p2["encoder"]
        say(f"  {p2['model']}: {enc.get('device')}, {enc.get('threads')} luồng, "
            f"cắt ở {enc.get('max_seq_length')} token, {enc.get('prompt_mode')}")
        for name in names:
            r = p2["datasets"].get(name)
            if r is None:
                say(f"    {name}: thiếu"); mark(False); continue
            nm = r["corpus_norm"]
            ok = abs(nm["norm_mean"] - 1) < 1e-3
            say(f"    {name}: corpus {tuple(r['corpus_shape'])}, query {tuple(r['query_shape'])}, "
                f"chuẩn {fmt(nm['norm_min'], 4)} đến {fmt(nm['norm_max'], 4)} ... {mark(ok)}")
            say(f"      góc tới GT5 {fmt(r['angles']['angle_mean'])}°, trùng top-5 với BGE "
                f"{fmt(100 * r['top5_overlap_with_bge'])}%, PQ m={r['pq_m']} MSE {fmt(r['pq_mse'], 4)}, "
                f"nhúng corpus {fmt(r['corpus_seconds'] / 60, 0)} phút")
    say()

    p3 = load("p3_scales")
    say("[p3] Corpus trung gian cho weak scaling (R1-3)")
    if p3 is None:
        say("  chưa chạy"); mark(False)
    else:
        ck = p3["checks"]
        say(f"  code và code50k là tiền tố của code100k ... {mark(ck['prefix20k_equal'] and ck['prefix50k_equal'])}")
        say(f"  query của code100k trùng bộ code (chênh lớn nhất {ck['queries_max_abs_diff']:.1e}) "
            f"... {mark(ck['queries_max_abs_diff'] < 1e-6, warn_only=True)}")
        rb = p3["rebuild_code50k"]
        say(f"  dựng lại code50k: top-10 trùng tập {fmt(100 * rb['gt_top10_identical_set'])}%, "
            f"trùng thứ tự {fmt(100 * rb['gt_top10_identical_order'])}% "
            f"... {mark(rb['gt_top10_identical_set'] >= 0.99)}")
        rel = abs(rb["pq_mse_rebuilt"] - rb["pq_mse_notebook"]) / rb["pq_mse_notebook"]
        say(f"  PQ m=512 của code50k: MSE notebook {fmt(rb['pq_mse_notebook'], 5)}, dựng lại "
            f"{fmt(rb['pq_mse_rebuilt'], 5)} ... {mark(rel < 0.05, warn_only=True)}")
        for name, r in p3["scales"].items():
            say(f"  {name}: {num(r['corpus'])} văn bản ({num(r['peers_at_2_docs_per_peer'])} peer), góc "
                f"{fmt(r['angles']['angle_mean'])}°, PQ MSE {fmt(r['pq_mse'], 5)}")
    say()

    p4 = load("p4_pq_variants")
    say("[p4] Codebook PQ cho sweep m (R1-1)")
    if p4 is None:
        say("  chưa chạy"); mark(False)
    else:
        for base, r in p4["corpora"].items():
            say(f"  {base}: MSE m=64 {fmt(r['m64_mse'], 4)} | m=128 {fmt(r['m128_mse'], 4)} | "
                f"m=256 {fmt(r['m256_existing_mse'], 4)} | m=512 {fmt(r['m512_existing_mse'], 4)} "
                f"... {mark(r['m64_mse'] > r['m128_mse'] > r['m256_existing_mse'] > r['m512_existing_mse'])}")
    say()

    if p1 is not None:
        say("Phiên bản thư viện: " + ", ".join(f"{k} {v}" for k, v in p1["versions"].items()))
    run = OUT.parent / "logs_prep" / "run.log"
    if run.exists():
        say()
        say("Thời gian từng bước:")
        for ln in run.read_text(encoding="utf-8").splitlines():
            if "mã thoát" in ln:
                say("  " + ln)
    say()
    say(f"KẾT LUẬN: {n_err} lỗi, {n_warn} cảnh báo")
    text = "\n".join(lines) + "\n"
    (OUT.parent / "prep_report.txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
