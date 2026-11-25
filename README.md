# V-Engram

Simulation code for the manuscript *V-Engram: Semantic Candidate Discovery in
Kademlia-Based Peer-to-Peer Overlays*, under revision at Peer-to-Peer
Networking and Applications.

V-Engram maps an embedding to `L` sign-random-projection sketches and uses each
complete sketch as a rendezvous target in the Kademlia identifier space. A query
probes `T` targets per table, searches a bounded neighborhood of `K` peers around
each target with Ripple Search, and lets the contacted peers rank their
discovery records with product-quantization codes. Kademlia's identifier space
and routing primitives are unchanged.

## Versions

| Tag | Manuscript | Experiments |
|---|---|---|
| `v2.0-r1` | revised manuscript (first revision) | batches in `ppna_r1/`, one tag `ppna-r1-*` per batch; see [`ppna_r1/README.md`](ppna_r1/README.md) |
| `v1.0-cc` (commit `b99bd9d`) | originally submitted manuscript | drivers `run_*.sh` and aggregation scripts `analyze_*.py` in the repository root |

## Layout

```
src/                   routing, network, and node models shared by all simulators
main_simulation.py     iterative Kademlia protocol: discrete-event simulation (SimPy) of
                       join, record placement, and Ripple Search; counts messages and rounds
main_simulation_v2.py  idealized closest-peer reference: every lookup returns the K
                       globally XOR-nearest reachable peers; used for large sweeps
main_churn_engine.py   idealized session churn and repair
main_churn_test.py     static peer loss: routable metadata and payload decodability
baselines.py           Bucket-LSH baseline
ppna_r1/               experiment batches of the revision
prepare/               construction of the original corpora, embeddings, and PQ codebooks
data/                  simulator inputs; see data/README.md
run_*.sh, analyze_*.py drivers and aggregation of the submitted manuscript
```

## Setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` covers the simulators (NumPy, SimPy, faiss). Computing
embeddings needs a separate environment (`ppna_r1/requirements_prep.txt`), and
the Semord comparison builds the authors' artifact outside the repository
(`ppna_r1/semord/setup_semord.sh`). [`ppna_r1/README.md`](ppna_r1/README.md)
describes both.

## Data

`data/` contains the processed CodeSearchNet (20,000 functions), SciFact (5,183
abstracts), and SQuAD v1.1 (18,891 passages) corpora with their BGE
embeddings, ground truth, and PQ codebooks. The larger code corpora, the
validation queries, and the e5 and jina embeddings are not tracked; `prepare/`
and `ppna_r1/prep/` rebuild them. [`data/README.md`](data/README.md) lists every
file, its origin, and its license.

```bash
ls data/code_corpus_embeddings.npy data/code_ground_truth.json   # sanity check
```

## Reproducing the revised manuscript

Every result of the revision comes from one of the batches in `ppna_r1/`. Run
each batch from its tag on a clean checkout, for example:

```bash
git checkout ppna-r1-dot3
sha256sum -c ppna_r1/SHA256SUMS_dot3
bash ppna_r1/run_dot3.sh
```

[`ppna_r1/README.md`](ppna_r1/README.md) gives the order of the batches, their
cost, and the source of every table and figure of the revised manuscript.

## Reproducing the submitted manuscript

```bash
git checkout v1.0-cc
```

and follow the README of that tag: the drivers `run_*.sh` produce the results,
and the `analyze_*.py` scripts print the reported numbers. The drivers are still
in the repository root, but the simulator has changed since, so the numbers of
the submission are reproduced from the tag.

## Seeds

Ten seeds are used throughout: `20235956, 1, 2, 3, 4, 5, 6, 7, 8, 9`. The first
is the primary seed and is the one used where a single run is reported. A seed
redraws peer identifiers and projection matrices; it does not change the corpus,
the query set, or the PQ codebook, all of which are fixed across seeds.

## Configuration flags

Behavior is selected by environment variable rather than by editing code, so
alternatives can be run from one binary. Several defaults are development
settings rather than paper settings. The drivers set every flag explicitly; for
the revision, the job list of each batch (`ppna_r1/<batch>/jobs.py`) gives the
exact command of every result.

| Variable | Values | Default | Meaning |
|---|---|---|---|
| `ROUTING_TABLE` | `kbucket`, `ring` | `ring` | `kbucket` is the Kademlia table the paper describes. `ring` is an earlier small-world construction, kept so the choice can be re-tested; the paper reports no results from it. |
| `BOOTSTRAP` | `join`, `oracle` | `join` | `join` has peers enter sequentially and learn contacts through real lookups. `oracle` hands each peer its globally nearest neighbors. |
| `K_BUCKET` | integer | `20` | k-bucket capacity. |
| `NUM_TABLES` | integer | `5` | Number of tables `L`. |
| `PROJ_FAMILY` | `achlioptas`, `gaussian` | `achlioptas` | Projection family. |
| `PQ_VARIANT` | `m512`, `m256`, and the variants built by `ppna_r1/prep` | `m512` | Product quantizer. |
| `STOP_RULE` | `stable`, `exhaust` | `stable` | Frontier-stability versus exhaustive top-K termination. |
| `FRONTIER_SCOPE` | `all`, `topk` | `all` | Whether the next peers to query come from the whole discovered candidate set or only the current frontier. |
| `R_MAX` | integer | `15` | Round cap of a lookup. |
| `JOIN_STOP_RULE`, `JOIN_FRONTIER_SCOPE`, `JOIN_R_MAX`, `INGEST_STOP_RULE`, `INGEST_FRONTIER_SCOPE`, `INGEST_R_MAX` | as above | unset | Termination rule of the join or ingestion phase. Unset, the phase uses `STOP_RULE`, `FRONTIER_SCOPE`, and `R_MAX`, so changing those changes all three phases. |
| `PROBE_ORDER` | `margin`, `random` | `margin` | Margin-ranked bit selection versus a random permutation of the same eligible positions. |
| `SHARED_ORIGIN` | `1`, `0` | `1` | Whether all `L·T` probes of a query share one origin peer. `0` reproduces an earlier bug. |
| `NORMALIZE_ROWS` | `1`, `0` | `1` | Whether projection columns are L2-normalized before margins are compared. `0` reproduces an earlier bug. |
| `MEASURE_OVERLAP` | `1`, `0` | `0` | Records XOR rank and inter-probe overlap. Expensive: it sorts the whole overlay per lookup. |
| `SKIP_PAYLOAD` | `1`, `0` | `0` | Skips payload retrieval, which the recall experiments do not need. |

The join of `main_simulation.py` is the reduced join of the submitted
manuscript: a sequential join and a second self-lookup. The standard Kademlia
join, which adds one round of bucket refresh, is `--join-refresh 1` in
`ppna_r1/dot2/iterative.py` and `JOIN_REFRESH=1` in `main_churn_test.py`; the
revised manuscript uses it for all protocol results.

Command-line defaults are development settings too: `--multi-probe 3` and
`--nq 100` against the paper's 8 and 500, and `--meta-anchors` unset against the
paper's 1.

## Known limitations of the model

Round-trip times are drawn independently from one distribution. There is no
bandwidth model, no serialization delay, no packet loss, and no queueing, so
simulated time is not a deployment latency; the manuscript argues from rounds,
RPCs, records, and evaluated peers.

Record signatures, Merkle proofs, and serialization are specified but not
executed; byte counts are analytical, derived from field widths. Under churn,
repair re-anchors discovery records only; payload shards are not repaired.

## License

The code is released under the MIT License (`LICENSE`). The files in `data/`
are derived from third-party datasets and keep the licenses of those datasets;
see `data/README.md`.

## Citation

Details will be added on acceptance.
