# `archive/`

Scripts and files of the submitted manuscript, kept for reference. They were
written for the code of release `v1.0-cc` (commit `b99bd9d`) and ran from the
repository root; the simulator has changed since. To rerun them, check out
`v1.0-cc`, where they are in the repository root, and follow the README of that
tag. Nothing in the revision (`ppna_r1/`) uses them.

| Folder | Content |
|---|---|
| `drivers/` | `run_*.sh`, the drivers of the submitted experiments, and `check_*.sh`, which report the progress of some of them |
| `analysis/` | `analyze_*.py`, which printed the submitted tables, and the other scripts that aggregated, measured, or checked results of that version |
| `manuscript/` | figures of an earlier draft with the script that drew them, a consistency check for the LaTeX source, and a converter between journal templates |

`patch_kbucket.py` installed the k-bucket routing table on an experimental
branch; that table is now part of `src/` (`ROUTING_TABLE=kbucket`).
`Compare_Method.md` is an early comparison, in Vietnamese, of V-Engram with
Kademlia, IPFS, Filecoin, and earlier semantic search systems.
