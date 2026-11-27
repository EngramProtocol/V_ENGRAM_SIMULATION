# Revision experiments (`ppna_r1/`)

This directory contains the experiments of the first revision of the manuscript
*V-Engram: Semantic Candidate Discovery in Kademlia-Based Peer-to-Peer
Overlays* (Peer-to-Peer Networking and Applications). Release `v2.0-r1`
contains all of them.

The experiments ran in batches. Each batch has a tag `ppna-r1-*`, one or more
run scripts `run_<batch>*.sh`, and a SHA-256 manifest `SHA256SUMS_<batch>` of
the files it ran with; the experiment batches dot1 to dot7 and semord also have
a job list and an aggregation script in `<batch>/`. The files
`README_<batch>.md` are the original operator notes of each batch. They, the
code comments, and the console messages in this directory are written in
Vietnamese and are kept unchanged because each batch manifest covers its own
notes; dot7, added after this documentation, is written in English. This file
documents the batches in English.

## Conventions

- **Seeds.** Every result of the revised manuscript uses the seeds 20235956
  and 1 to 9; the verification batches also use subsets of them.
- **Evaluation models.** The *iterative protocol* simulates join, record
  placement, and Ripple Search with SimPy (`dot2/iterative.py` on top of `src/`
  and `main_simulation.py`). The *idealized closest-peer reference*
  (`main_simulation_v2.py`) returns the `K` globally XOR-nearest reachable peers
  for every lookup.
- **Joins.** The *standard join* is the sequential join followed by one round
  of bucket refresh, in which every peer refreshes all k-buckets farther away
  than its closest neighbor by looking up a random identifier in each of them,
  as specified for Kademlia. It is `--join-refresh 1` in `dot2/iterative.py`
  and `JOIN_REFRESH=1` in `main_churn_test.py`. The *reduced join* omits the
  refresh and replaces it by a second self-lookup; it is the join of the
  submitted manuscript, which the revision reports as a sensitivity analysis.
- **Clean checkouts.** The run scripts of dot1 to dot7 and semord stop if a
  tracked file is modified, and record the commit they ran from in their logs.
  Each job they start through `dot1/runner.py` also writes that commit to a
  `.ok` file beside its result, and a rerun skips only the jobs finished with
  the same commit. The prep and verification scripts record the commit and any
  modified file in `logs_<batch>/env.txt` but do not stop. Run each batch from
  its tag.
- **Table numbers in the reports.** The aggregation scripts were written
  before the revised manuscript was assembled. Their reports number tables as
  in the submitted manuscript ("Bảng N" means Table N of the submitted
  version); the table at the end of this file gives the revised numbers.

## Batches

| Batch | Tag | Run script | Jobs | Content |
|---|---|---|---|---|
| verify-norm | `ppna-r1-verify-norm` | `run_verify_norm.sh` | 46 | Whether the submitted reference results predate the normalization of projection columns, and how much the normalization changes them |
| verify-s2 | `ppna-r1-verify-s2` | `run_verify_s2.sh` | 144 | Checks made while planning the revision: rows of the submission that averaged five seeds, termination rules changed in the query phase only, availability on a seeded k-bucket overlay |
| prep | `ppna-r1-prep`, `ppna-r1-dot1` | `run_prep.sh` | 5 steps | Validation queries, intermediate code corpora, PQ codebooks with `m` = 64 and 128, e5-large-v2 and jina-code-embeddings-0.5b embeddings |
| dot1 | `ppna-r1-dot1` | `run_dot1.sh` | 1,875 | Reference model: all tables at ten seeds, design sensitivity, additional workloads, truncated keys, Bucket-LSH widths selected on validation queries, availability with the reduced join, idealized churn |
| dot2 | `ppna-r1-dot2` | `run_dot2.sh` | 150 | Protocol with the reduced join: termination, controls, factorial decomposition of the difference between the two models, Bucket-LSH, peer loss, 25,000 peers, the (`c`, `T`) pair, margin ablation; reference: per-table statistics of Gaussian projections, budget sweep for jina |
| dot3 | `ppna-r1-dot3` | `run_dot3.sh` | 220 | Protocol: `T` and `K` sweep, 50,000 peers, additional workloads, the standard join, and a replica of every protocol experiment with the standard join |
| dot4 | `ppna-r1-dot4` | `run_dot4.sh` | 80 | Protocol: `L` = 8 with `T` = 8 and `T` = 5, both joins |
| dot5 | `ppna-r1-dot5`, `ppna-r1-dot5b` | `run_dot5.sh` | 30 | Session churn on the protocol; `dot5b` adds the no-churn Recall@5 of both models (`dot5/ideal_t0.py`) and corrects the aggregation |
| dot6 | `ppna-r1-dot6` | `run_dot6.sh` | 61 | Availability under static peer loss with the standard join, on the same failed peers as dot1 |
| semord | `ppna-r1-semord`, `-semord2`, `-semord3`, `-semord5` | `run_semord.sh`, `run_semord_n2000.sh`, `run_semord_l8.sh` | 418 | Comparison with Semord, using the authors' artifact: 338 Semord runs and 80 V-Engram jobs |
| dot7 | `ppna-r1-dot7` | `run_dot7.sh` | 60 | Reference model: 4, 6, and 8 bits per PQ index at `m` = 512 on both corpora; data step p5 (`prep/p5_pq_bits.py`) builds the codebooks |

The single-core cost of the larger batches was about 75 hours for dot1
(including the second pass after the embeddings), 28 hours for dot2, 76 hours
for dot3, 13 hours for dot4, and 12 hours for dot5. On an eight-core CPU, the
e5 embeddings took about five hours and the jina embeddings about three hours.
The Semord comparison took about ten hours.

## Running the batches

Use the simulator environment of the repository root (`requirements.txt`) for
every batch except the embeddings. The embedding step uses its own environment,
which `run_dot7.sh` also uses for data step p5 when it exists:

```bash
python3 -m venv venv_prep
venv_prep/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
venv_prep/bin/pip install -r ppna_r1/requirements_prep.txt
```

Each batch is run from the repository root on a clean checkout of its tag:

```bash
git checkout <tag>
sha256sum -c ppna_r1/SHA256SUMS_<batch>
source venv/bin/activate
bash ppna_r1/run_<batch>.sh
```

A manifest verifies at its own tag. Later batches changed some shared files,
so an earlier manifest does not verify at a later commit.

Run scripts write logs to `ppna_r1/logs_<batch>*/` and a report to
`ppna_r1/<batch>_report*.txt`. The experiment batches write their results to
`ppna_r1/out_<batch>/` and a summary to `ppna_r1/<batch>_summary*.json`; prep
writes the files it builds to `data/`. A script that is interrupted resumes
when it is run again (verify-norm only with `SKIP_DONE=1`). `PARALLEL=n` bounds
the number of concurrent jobs (default: the number of cores minus one, or 4 for
the verification batches).

Later batches read the outputs of earlier ones, so run them in this order:

1. **prep and dot1**, both from `ppna-r1-dot1`: `run_prep.sh`, then
   `run_dot1.sh`. Steps p1, p3, and p4 of prep first ran from `ppna-r1-prep`;
   the code at `ppna-r1-dot1` differs only in the embedding step, which loads
   jina in float32. dot1 also compares its results with those of verify-norm
   and verify-s2 when their outputs are present.
2. **dot2**, which reads the Bucket-LSH widths that dot1 selected on
   validation queries.
3. **dot3**, which reads the outputs of dot1 and dot2.
4. **dot4, dot5, and dot6**, in any order. dot5 reads the idealized churn runs
   of dot1 and the static runs of dot3; `ppna-r1-dot5b` contains the final
   version of `run_dot5.sh` and its aggregation. dot6 reads the availability
   runs of dot1.
5. **semord**, from `ppna-r1-semord5`: `run_semord.sh` (1,000 peers),
   `run_semord_n2000.sh` (2,000 peers), and `run_semord_l8.sh` (`L` = 8 at
   both sizes). `semord/setup_semord.sh` clones and builds the authors'
   LearnedHash (commit `542528c8`) and Vortex_system (commit `8766ddb5`) in
   `$SEMORD_ROOT` (default `~/semord_src`), outside the repository. It needs
   git, make, a C++20 compiler (GCC 10 or later), pip, and about 3 GB of disk;
   it installs cmake with pip and builds OpenBLAS when the system has none.
   The only change to the artifact is `semord/learnedhash_linux.patch`, which
   resolves an ambiguous constructor call that fails to compile on Linux. The
   VHash configurations chosen by the authors' selector are fixed in
   `semord/sel/`, because the selector scores measured time and may choose
   differently on another run. The operator notes call the state that added
   the 2,000-peer runs `ppna-r1-semord4`; this repository has no such tag, and
   that commit is part of `ppna-r1-semord5`.
6. **dot7**, from `ppna-r1-dot7`. It reads the results of dot1 (group `t4`
   for its regression check and group `r11` for the comparisons with
   `m` = 256 and exact ranking), and its first stage runs data step p5 in the
   prep environment, which writes the codebooks with 4 and 6 bits per index
   to `data/`.

## Sources of the tables and figures of the revised manuscript

Section numbers refer to the report of each batch, for example `§8` of
`dot3_report.txt`. Where a cell combines two batches, such as a paired
difference between the protocol and the reference at the same seed, the
reports list the values from which it is computed.

| Revised manuscript | Submitted manuscript | Sources |
|---|---|---|
| Table 4, routing state and recall by join | new | dot3 §5; dot2 §10 (rounds, routing and evaluation RPCs) |
| Section 4.2 and Table 5, agreement of the two models | new | dot3 §5 and §8; dot1 §5 with dot3 §8 (Bucket-LSH); dot4 (`L` = 8) |
| Table 6, semantic targets and controls | Table 4 | dot1 §2; dot3 §8 (protocol); dot2 §4 (reduced join) |
| Table 7 and Fig. 2, `T` and `K` | Table 5, Fig. 2 | dot1 §4; dot3 §8 (protocol); dot3 §2 (reduced join) |
| Section 4.4, correlation between tables | text | dot1 §3 |
| Table 8, Bucket-LSH | Table 6 | dot1 §5; dot3 §8 (protocol); dot2 §5 and dot3 §6 (reduced join) |
| Section 4.5, margin-ranked probing | text | dot3 §8 (protocol); dot2 §9 (reduced join) |
| Table 9, Semord at 1,000 peers | new | semord: `semord_report.txt`, `semord_report_l8_n1000.txt` |
| Table 10, termination | Table 7 | dot3 §5 and §8 (standard join); dot2 §2 (reduced join) |
| Table 11, design sensitivity | new | dot1 §12; dot7 (bits per PQ index); dot3 §8 (`c` = 9, `T` = 5 on the protocol); dot4 (`L` = 8 on the protocol) |
| Table 12, additional workloads | new | prep (embeddings); dot1 §14; dot3 §8 (protocol); dot3 §4 (reduced join) |
| Table 13, replication | Table 8 | dot1 §6; dot3 §8 (`r` = 2 and 3 on the protocol) |
| Table 14, static peer loss | Table 9 | dot1 §7 (reference); dot3 §8 (protocol recall); dot6 (availability) |
| Table 15 and Fig. 3, session churn | Table 10, Fig. 3 | dot5; dot1 §8 (idealized engine) |
| Table 16, weak scaling | Table 11 | dot1 §9; dot3 §8 (protocol); dot2 §7 and dot3 §3 (reduced join) |
| Fig. 4, load as the overlay grows | Fig. 4 | dot1 §9 |
| Table 17, peer-local work | Table 12 | dot1 §10 |
| Table 18, operating points | new | dot3 §8 and `dot3_summary.json` (standard join); dot4 (`L` = 8) |
| Equation 30, expected coverage | new | dot1 §16; predictions written before the runs to `dot1/predictions_dot1.json` by `dot1/predict_coverage.py` |
| Section 4.1, peer-local cap κ | text | dot1 §11 |
| Table A1, factorial decomposition | new | dot2 §3 |
| Table A2, results with the reduced join | new | dot2 §2 to §9; dot3 §2 to §4 and the "cũ" (reduced join) column of §8; dot4 |
| Table A3, availability by join | new | dot6 |
| Table B1, estimates at five, seven, and ten seeds | new | dot1 §17 (reference); per-seed results of dot3 §8 (protocol) |
| Table C1, Bucket-LSH width sweep | new | dot1 §5 |
| Table D1, Semord at 2,000 peers | new | semord: `semord_report_n2000.txt`, `semord_report_l8_n2000.txt` |
| Table D2, Semord peer budgets | new | semord: `semord_report.txt`, `semord_report_n2000.txt` |
| Table E1, per-bit agreement with 1 − θ/π | new | dot1 §13 (`dot1/bit_collision.py`) |
| Table E2, Gaussian projections | new | dot1 §12; dot2 §11 |
| Table E3, truncated keys | new | dot1 §15 |
| Table E4, budget sweep for jina | new | dot2 §12 |
| Table F1, idealized churn engine | new | dot1 §8 |
| Table F2, cost of churn on the protocol | new | dot5 |
| Values changed from the submitted manuscript | | dot1 §18 |

## Earlier results

The drivers `run_*.sh` and aggregation scripts `analyze_*.py` that produced the
results of the submitted manuscript are kept in `archive/`. They run from
release `v1.0-cc`, where they are in the repository root.
