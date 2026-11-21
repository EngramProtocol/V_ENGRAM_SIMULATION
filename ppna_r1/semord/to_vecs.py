"""Chuyển embedding và ground truth của V-Engram sang định dạng fvecs/ivecs cho artifact Semord.
Vector đã chuẩn hoá L2 nên khoảng cách L2 xếp hạng đúng như cosine."""
import json, sys, os
import numpy as np

def write_fvecs(path, X):
    X = np.ascontiguousarray(X, dtype=np.float32)
    n, d = X.shape
    out = np.empty((n, d + 1), dtype=np.float32)
    out[:, 0] = np.frombuffer(np.int32(d).tobytes(), dtype=np.float32)[0]
    out[:, 1:] = X
    out.tofile(path)

def write_ivecs(path, I):
    I = np.ascontiguousarray(I, dtype=np.int32)
    n, k = I.shape
    out = np.empty((n, k + 1), dtype=np.int32)
    out[:, 0] = k
    out[:, 1:] = I
    out.tofile(path)

def gt_ids(gt, key):
    return np.array([[r['index'] for r in x[key]] for x in gt], dtype=np.int32)

if __name__ == '__main__':
    data_dir, out_root = sys.argv[1], sys.argv[2]
    for ds in ('code', 'scifact'):
        o = os.path.join(out_root, ds); os.makedirs(o, exist_ok=True)
        E = np.load(f'{data_dir}/{ds}_corpus_embeddings.npy').astype(np.float32)
        Q = np.load(f'{data_dir}/{ds}_query_embeddings.npy').astype(np.float32)
        gt = json.load(open(f'{data_dir}/{ds}_ground_truth.json', encoding='utf-8'))
        assert np.allclose(np.linalg.norm(E, axis=1), 1, atol=1e-3) and np.allclose(np.linalg.norm(Q, axis=1), 1, atol=1e-3)
        G10 = gt_ids(gt, 'top_10_results')
        # kiểm: top-5 của GT là 5 phần tử đầu của top-10, và khớp cosine chính xác
        assert (gt_ids(gt, 'top_5_results') == G10[:, :5]).all()
        S = Q @ E.T
        ex = np.argsort(-S, axis=1)[:, :10]
        agree = np.mean([len(set(ex[i, :5]) & set(G10[i, :5])) / 5 for i in range(len(Q))])
        write_fvecs(f'{o}/{ds}_base.fvecs', E)
        write_fvecs(f'{o}/{ds}_query.fvecs', Q)
        write_ivecs(f'{o}/{ds}_groundtruth.ivecs', G10)
        vq = f'{data_dir}/{ds}_val_query_embeddings.npy'
        if os.path.exists(vq):
            V = np.load(vq).astype(np.float32)
            vg = json.load(open(f'{data_dir}/{ds}_val_ground_truth.json', encoding='utf-8'))
            write_fvecs(f'{o}/{ds}_val_query.fvecs', V)
            write_ivecs(f'{o}/{ds}_val_groundtruth.ivecs', gt_ids(vg, 'top_10_results'))
            print(ds, 'validation', V.shape)
        print(ds, E.shape, Q.shape, 'GT10', G10.shape, 'exact top5 agree', agree)
