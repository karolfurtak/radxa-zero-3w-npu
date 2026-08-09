#!/usr/bin/env python3
"""
quality_diag.py -- small, fast, low-thermal-risk diagnostic to isolate WHY the NPU int8
model showed recall@3 = 0.051 vs CPU fp32 (near-random for k=3 among 600 candidates)
while CPU int8 showed 0.85. Adds a THIRD point: NPU fp16 (no int8 quantization, same
RKNN toolchain/masking/padding path). If fp16 also collapses -> conversion/masking bug,
not quantization. If fp16 is fine -> the w8a8 int8 quantization is the culprit (needs a
larger/more diverse calibration set or per-channel/mixed precision, not usable as-is).

N=60 only -- this is a correctness probe, not a speed benchmark, kept short on purpose
after the previous run's thermal incident.
"""
import json
import os
import time
from pathlib import Path

import numpy as np
from tokenizers import Tokenizer

BASE = Path(__file__).parent
SEQ_LEN = 64
N = 60
TOKENIZER_PATH = str(BASE / "tokenizer.json")
ONNX_FP32 = str(BASE / "model.onnx")
RKNN_INT8 = str(BASE / "model_int8_rk3566.rknn")
RKNN_FP16 = str(BASE / "model_fp16_rk3566.rknn")
SAMPLE_PATH = BASE / "sample_600.jsonl"
OUT_PATH = BASE / "wyniki_jakosc_diag.json"

os.nice(15)
try:
    Path("/proc/self/oom_score_adj").write_text("500")
except Exception:
    pass

with open(SAMPLE_PATH, encoding="utf-8") as f:
    SENTENCES = [json.loads(l)["text"] for l in f][:N]


def tokenizuj(tok, s):
    tok.enable_padding(length=SEQ_LEN, pad_id=0)
    tok.enable_truncation(max_length=SEQ_LEN)
    enc = tok.encode(s)
    ids = np.array([enc.ids], dtype=np.int64)
    mask = np.array([enc.attention_mask], dtype=np.int64)
    typ = np.zeros_like(ids)
    return ids, mask, typ


def mean_pool(h, mask):
    m = mask[..., None].astype(np.float32)
    return ((h * m).sum(1) / np.clip(m.sum(1), 1e-9, None))[0]


def embed_cpu(onnx_path):
    import onnxruntime as ort
    tok = Tokenizer.from_file(TOKENIZER_PATH)
    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    out = []
    for s in SENTENCES:
        ids, mask, typ = tokenizuj(tok, s)
        (h,) = sess.run(None, {"input_ids": ids, "attention_mask": mask, "token_type_ids": typ})
        out.append(mean_pool(h, mask))
    return out


def embed_npu(rknn_path):
    from rknnlite.api import RKNNLite
    tok = Tokenizer.from_file(TOKENIZER_PATH)
    rknn = RKNNLite()
    assert rknn.load_rknn(rknn_path) == 0
    assert rknn.init_runtime() == 0
    out = []
    for s in SENTENCES:
        ids, mask, typ = tokenizuj(tok, s)
        h = rknn.inference(inputs=[ids, mask, typ])[0]
        out.append(mean_pool(h, mask))
    rknn.release()
    return out


def topk(mat, i, k):
    sims = mat @ mat[i] / (np.linalg.norm(mat, axis=1) * np.linalg.norm(mat[i]) + 1e-9)
    order = np.argsort(-sims)
    return set([j for j in order if j != i][:k])


def recall_at_k(ref, test, k=3):
    ref, test = np.array(ref), np.array(test)
    hit = poss = 0
    for i in range(len(ref)):
        hit += len(topk(ref, i, k) & topk(test, i, k))
        poss += k
    return round(hit / poss, 3)


if __name__ == "__main__":
    print("embedding: cpu fp32 (reference)", flush=True)
    e_fp32 = embed_cpu(ONNX_FP32)

    print("embedding: npu int8", flush=True)
    e_npu_int8 = embed_npu(RKNN_INT8)

    print("embedding: npu fp16 (no quantization -- isolates the cause)", flush=True)
    e_npu_fp16 = embed_npu(RKNN_FP16)

    wyniki = {
        "n_zdan": N,
        "recall_at_3_npu_int8_vs_cpu_fp32": recall_at_k(e_fp32, e_npu_int8, 3),
        "recall_at_3_npu_fp16_vs_cpu_fp32": recall_at_k(e_fp32, e_npu_fp16, 3),
        "interpretacja": (
            "jesli fp16 wysoki a int8 niski -> wina kwantyzacji w8a8 (kalibracja/precyzja); "
            "jesli oba niskie -> blad w konwersji/maskowaniu, nie w samej kwantyzacji"
        ),
    }
    OUT_PATH.write_text(json.dumps(wyniki, indent=2, ensure_ascii=False))
    print(json.dumps(wyniki, indent=2, ensure_ascii=False))
