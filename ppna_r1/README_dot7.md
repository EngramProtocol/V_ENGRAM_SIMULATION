# Batch dot7: bits per PQ index (tag `ppna-r1-dot7`)

## Purpose

Comment 1.1 of Reviewer 1 asks for a justification of the PQ parameters `m = 512` and `q = 8`.
Batch dot1 varied `m` at 8 bits per index (group `r11`: `m` = 64, 128, 256, and exact cosine ranking
without PQ). This batch varies the bits per index `q_PQ` at `m = 512`: 4, 6, and 8 bits, on
CodeSearchNet and SciFact, under the idealized closest-peer reference with the principal
configuration and the ten seeds. The discovery record is `168 + ceil(m q_PQ / 8)` bytes: 680 bytes at
8 bits, 552 at 6, and 424 at 4, the same as `m = 256` at 8 bits.

## Data step p5

`ppna_r1/prep/p5_pq_bits.py` trains the PQ codebooks with 4 and 6 bits per index (16 and 64 centroids
per two-dimensional subquantizer) with `train_pq` of `ppna_r1/prep/common.py`, the routine of prep step
p4 (`faiss.ProductQuantizer`, k-means seed 1234), and writes

```
data/{code,scifact}_pq_codebook_m512q{4,6}.npy   (512, 2**q, 2) float32
data/{code,scifact}_pq_codes_m512q{4,6}.npy      (N, 512) uint8, one index per byte
```

faiss packs indices shorter than 8 bits into `ceil(m q / 8)` bytes per object, least significant
bit first. The simulator looks up one index per subquantizer, so the codes are stored unpacked; the
record size counts the packed size. Two checks guard the unpacking: the reconstruction error computed
from the unpacked indices equals the one faiss computes from the packed codes, and every index is a
nearest centroid of its subvector. The step also retrains 8 bits per index with the same routine and
compares the result with the shipped codebook `data/*_pq_codebook_m512.npy`, so that the report shows
whether all three codebooks come from one procedure. It writes `ppna_r1/out_dot7/pq_bits.json` and
nothing for 8 bits.

The step runs in the prep environment `venv_prep` by default, like p4. It is skipped once
`ppna_r1/logs_dot7/prep.ok` exists, so a rerun of the batch never replaces the codebooks that the
results were computed with.

## Jobs

`dot7/jobs.py` lists 60 jobs of `main_simulation_v2.py` (group `pq`): the principal configuration of
dot1 group `t4` (10,000 peers, `L = 5`, `T = 8`, `K = 20`, `r = 1`, `c = 16`, `kappa = 30`, 500 test
queries, column-normalized Achlioptas projections, per-table statistics) with `--pq-variant m512q4`,
`m512q6`, or `m512`, on both corpora and the ten seeds. The `q = 8` jobs repeat the command of `t4`
(semantic) with another output file, so their recall must equal the results of dot1. The smoke group
`sm` runs 4 and 6 bits on both corpora with 2,000 peers and 5 queries. Nothing in the simulator
changes: it reads the shape of the codebook and indexes its lookup table with the stored indices.

## Report

`dot7/aggregate.py` writes `ppna_r1/dot7_report.txt` and `ppna_r1/dot7_summary.json`:

1. codebooks: centroids, packed code size, record size, codebook size, reconstruction error, and the
   checks of p5;
2. regression of `q = 8` against `ppna_r1/out_dot1/t4`: recall, reachable recall, peers, record load,
   and RPC counts must be identical; the correlation summaries and the mean number of unique
   candidates may differ slightly between numpy builds and are listed with their largest absolute and
   relative differences;
3. routing and placement do not read the codes, so reachable Recall@5, evaluated peers, record load,
   and RPC counts must be identical for every `q` at one seed;
4. Final Recall@5 for each `q`, mean and SD over the seeds, and the paired difference from `q = 8` with
   its 95% confidence interval;
5. from dot1 group `r11`, paired by seed: `m = 512` with 4 bits against `m = 256` with 8 bits (both
   256-byte codes), and exact cosine ranking against each `q`.

## Running

From the repository root, on a clean checkout of the tag:

```bash
git checkout ppna-r1-dot7
sha256sum -c ppna_r1/SHA256SUMS_dot7
source venv/bin/activate
tmux new -s dot7 -d "bash ppna_r1/run_dot7.sh"
```

Stages: `prep` (data step p5), `smoke`, `run` (60 jobs), `report`. Options: `PARALLEL` (default: the
number of cores minus one), `PY`, `PY_PREP` (default `venv_prep/bin/python`; any Python with
faiss-cpu works), `REF_ROOT` (default `ppna_r1/out_dot1`), `SEEDS`. On two cores, p5 took about 5
minutes and a job 13 to 30 seconds; the batch costs about 20 minutes on one core.

Results: `ppna_r1/dot7_report.txt`, `ppna_r1/dot7_summary.json`, `ppna_r1/out_dot7/`, and the logs in
`ppna_r1/logs_dot7/`.
