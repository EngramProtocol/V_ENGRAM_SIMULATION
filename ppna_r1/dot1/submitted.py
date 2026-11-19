"""Số liệu của bản đã nộp PPNA (V_ENGRAM_7.pdf), để lập bảng thay đổi số liệu.

Mỗi số ghi đúng như in trong bài. Bảng 9 cột availability và Bảng 10 trong bản đã
nộp lần lượt là một seed (overlay ring) và ba seed; Bảng 11 các điểm 25k, 50k là
năm seed; Bảng 8 cột random là ước lượng điểm.
"""

# Bảng 4: (R@5, SD, Peers %, Cand. %)
T4 = {
    'code': {
        'semantic': (80.0, 4.8, 4.9, 22.5),
        'random_unique': (22.1, 1.3, 4.9, 14.4),
        'random_keys': (33.4, 1.7, 7.7, 22.2),
        'random_slots': (34.5, 0.9, 8.0, 22.6),
        'random_equalcand': (47.4, 9.6, 12.6, 32.7),
    },
    'scifact': {
        'semantic': (80.0, 4.9, 4.9, 35.6),
        'random_unique': (22.2, 0.7, 4.9, 17.3),
        'random_keys': (33.7, 1.2, 7.7, 26.5),
        'random_slots': (33.9, 1.3, 8.0, 26.9),
        'random_equalcand': (55.5, 7.8, 16.1, 45.9),
    },
}
MODE_LABEL = {
    'semantic': 'Semantic targets', 'random_unique': 'Random, equal peers',
    'random_keys': 'Random keyed', 'random_slots': 'Random, nominal',
    'random_equalcand': 'Random, candidate threshold',
}

# Bảng 5: (T, K) -> (Reach R@5, Final R@5, Peers %, Cand. %)
T5 = {
    (1, 20): (39.9, 39.8, 1.0, 5.7), (3, 20): (60.6, 60.1, 2.1, 11.2),
    (5, 20): (72.2, 71.3, 3.3, 16.1), (8, 20): (81.6, 80.0, 4.9, 22.5),
    (12, 20): (87.6, 85.4, 7.0, 29.7), (8, 10): (74.0, 73.0, 2.7, 14.5),
    (8, 40): (88.6, 86.3, 8.9, 33.4), (8, 80): (94.7, 91.7, 15.7, 48.3),
}

# Bảng 6: Bucket-LSH T -> (b_LSH mode, Candidates, R@5, SD); V-Engram -> (Candidates, R@5, SD)
T6 = {
    'code': {1: (8, 3143, 43.0, 7.5), 4: (10, 4444, 61.1, 6.6), 8: (12, 4578, 63.4, 5.0),
             'vengram': (4510, 80.0, 4.8)},
    'scifact': {1: (8, 977, 43.1, 5.8), 4: (10, 1808, 66.2, 5.4), 8: (10, 1787, 66.4, 5.2),
                'vengram': (1845, 80.0, 4.9)},
}
T6_GAIN = {'code': 16.6, 'scifact': 13.6}     # V-Engram hơn Bucket-LSH T = 8 (Abstract, Mục 4.4)

# Bảng 8: semantic (R@5, SD); random nominal (điểm)
T8_SEM = {1: (80.0, 4.8), 2: (80.3, 4.7), 4: (80.6, 4.6), 5: (80.8, 4.5), 10: (81.6, 4.4)}
T8_RND = {1: 34.5, 2: 56.4, 4: 79.8, 5: 85.4, 10: 94.9}

# Bảng 9: (r, loss) -> (Final R@5, SD, routable metadata %, routable payload %)
T9 = {
    (1, 0.0): (80.0, 4.8, 99.9, 100.0), (1, 0.2): (74.6, 5.0, 99.4, 96.7),
    (1, 0.3): (71.5, 5.0, 98.0, 74.5), (2, 0.3): (80.9, 4.6, 99.8, 74.6),
    (3, 0.3): (82.8, 4.1, 99.9, 72.1),
}

# Bảng 10: (r, chu kỳ sửa) -> (Min. metadata, R@5, Live copies, Msg./obj.)
T10 = {
    (1, 0): (57.5, 23.7, 0.79, 0.0),
    (1, 480): (99.2, 84.6, 5.77, 13.8),
    (4, 1320): (99.8, 85.3, 21.99, 20.0),
}
T10_TTL_TEXT = 1.5   # Mục 4.7 viết TTL = 1,5 chu kỳ sửa

# Bảng 11: (N, K) -> (R@5, SD, Peers %, Cand. %)
T11 = {
    (10000, 20): (80.0, 4.8, 4.9, 22.5),
    (25000, 20): (71.8, 8.4, 2.2, 11.3), (50000, 20): (65.2, 8.9, 1.2, 6.5),
    (25000, 50): (81.2, 5.8, 4.9, 20.8), (50000, 100): (82.2, 5.7, 4.9, 19.4),
}

# Bảng 12: (Gini, SD, max/mean, SD)
T12 = {
    'records': (0.78, 0.04, 116, 52),
    'adc': (0.49, 0.08, 9, 3),
    'scan': (0.90, 0.03, 380, 225),
}
# Hình 4b: N -> (Gini tải quét record, max/mean), K tăng theo N
FIG4B = {10000: (0.90, 380), 25000: (0.93, 723), 50000: (0.95, 1523)}

# Số trong văn bản
TEXT = {
    'table_pair_corr': 0.014,            # Mục 4.3: tương quan cặp bảng trung bình
    'reach_final_gap': (0.1, 3.0),       # Mục 4.3: khoảng Reachable - Final trên sweep lý tưởng
    'per_table_spread': 3.0,             # Mục 5.3: reachability từng bảng chênh gần ba lần
}
