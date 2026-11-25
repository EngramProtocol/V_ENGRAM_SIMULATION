# `data/`

Inputs read by the simulators. The files of the three corpora below are tracked
in git. All other inputs are rebuilt by `prepare/` or `ppna_r1/prep/` and are
ignored by git.

## Tracked files

| Corpus | Source | Documents | Queries |
|---|---|---|---|
| `code` | CodeSearchNet, Python train split | 20,000 functions with the docstring removed | first sentence of the docstring |
| `scifact` | SciFact, BEIR version | 5,183 abstracts (title and text) | 500 claims |
| `squad` | SQuAD v1.1 | 18,891 passages | 500 questions |

For each corpus `{name}`:

| File | Content |
|---|---|
| `{name}_corpus_texts.json` | corpus strings, index-aligned with the embeddings |
| `{name}_corpus_embeddings.npy` | BAAI/bge-large-en-v1.5 embeddings, float32, L2-normalized, 1024 dimensions |
| `{name}_query_embeddings.npy` | embeddings of the 500 test queries |
| `{name}_ground_truth.json` | exact top-10 corpus entries per query, with cosine similarities |
| `{name}_pq_codebook_m512.npy`, `{name}_pq_codes_m512.npy` | product quantizer with `m` = 512 subquantizers of two dimensions, used in the manuscript |
| `{name}_pq_codebook.npy`, `{name}_pq_codes.npy` | earlier product quantizer with `m` = 256 subquantizers of four dimensions |

`manifest.json` records the corpus size, the number of queries, and the mean
angle between a query and its ground-truth neighbors for each corpus.
`prepare/README.md` describes how these files were built.

## Rebuilt files (not tracked)

| Files | Built by |
|---|---|
| `code50k_*`, `code100k_*` | `prepare/02_extend_weakscaling.ipynb` |
| `code30k_*`, `code40k_*`, `code70k_*` | `ppna_r1/prep/p3_scales.py` |
| `code_val_*`, `scifact_val_*` (500 validation queries per corpus) | `ppna_r1/prep/p1_validation.py` |
| `*_pq_codebook_m64.npy`, `*_pq_codes_m64.npy`, and the `m128` variants | `ppna_r1/prep/p4_pq_variants.py` |
| `code_e5_*`, `scifact_e5_*`, `code_jina_*` | `ppna_r1/prep/p2_models.py` |
| `manifest_r1.json` | `ppna_r1/prep/` |

`code100k_corpus_embeddings.npy` alone is 410 MB, above GitHub's per-file
limit, which is why the larger corpora are not tracked.

## Licenses

The files in this directory are derived from third-party datasets and are not
covered by the MIT License of the code. They remain under the terms of their
sources:

- CodeSearchNet (Husain et al., 2019): every function comes from a public
  GitHub repository and remains under the license of that repository.
- SciFact (Wadden et al., 2020): CC BY-NC 2.0.
- SQuAD v1.1 (Rajpurkar et al., 2016): CC BY-SA 4.0.

The embeddings were computed with BAAI/bge-large-en-v1.5, which is released
under the MIT License. The rebuilt e5 embeddings use intfloat/e5-large-v2 (MIT
License), and the jina embeddings use jinaai/jina-code-embeddings-0.5b, which
is released under a non-commercial license.
