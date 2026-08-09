#!/usr/bin/env python3
"""
convert_to_rknn.py — ONNX -> RKNN (target: rk3566) for
sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (Apache-2.0, see
MODEL-LICENSE.md), quantized to int8 with a calibration set of real sentences.

Why this script is published instead of the .rknn file: the converted model is
~120 MB, over plain git's 100 MB per-file limit (would require Git LFS for a
documentation-only repo). Anyone with the RKNN Toolkit can reproduce the exact
file below in a few minutes — that's a better fit for this repo than a binary
blob it can't natively host.

Requires: rknn-toolkit2 (pip), Python 3.10/3.11/3.12, an x86_64 or aarch64 Linux
host (the toolkit does NOT need to run on the Radxa itself — cross-conversion on
a bigger machine is the standard, and lighter-weight, workflow). Output runs on
the board via the separate `rknn-toolkit-lite2` runtime package.

    pip install rknn-toolkit2==2.3.2 "setuptools<81" tokenizers onnx

Get the source ONNX export + tokenizer (already exported by the Xenova project,
same weights as the original PyTorch checkpoint):

    https://huggingface.co/Xenova/paraphrase-multilingual-MiniLM-L12-v2
    -> onnx/model.onnx, tokenizer.json

Calibration data: replace CALIB_SENTENCES with ~100-300 sentences representative
of your real workload (language mix, length distribution). Quantization ranges
are fit to whatever you calibrate on — calibrating on the wrong distribution is
a silent, hard-to-detect way to get a technically-working but poorly-quantized
model.
"""
import os

import numpy as np
from tokenizers import Tokenizer
from rknn.api import RKNN

SEQ_LEN = 64  # covers ~90th percentile of real-sentence token length at this model's tokenizer
MODEL_DIR = "model"          # put model.onnx + tokenizer.json here
ONNX_PATH = f"{MODEL_DIR}/model.onnx"
CALIB_NPY_DIR = "calib_npy"
DATASET_TXT = "dataset.txt"
OUT_RKNN = "model_int8_rk3566.rknn"

# Replace with real, representative sentences from your own corpus.
CALIB_SENTENCES = [
    "Ciśnienie parcjalne tlenu maleje wraz ze wzrostem wysokości nad poziomem morza.",
    "The mitochondria is the powerhouse of the cell, generating ATP through oxidative phosphorylation.",
    "Prawo Ohma opisuje zależność między napięciem, natężeniem prądu i rezystancją w obwodzie.",
    # ... 100-300 total sentences recommended
]


def build_calibration_dataset(tok: Tokenizer) -> None:
    os.makedirs(CALIB_NPY_DIR, exist_ok=True)
    tok.enable_padding(length=SEQ_LEN, pad_id=0)
    tok.enable_truncation(max_length=SEQ_LEN)

    lines = []
    for i, sentence in enumerate(CALIB_SENTENCES):
        enc = tok.encode(sentence)
        input_ids = np.array([enc.ids], dtype=np.int64)
        attention_mask = np.array([enc.attention_mask], dtype=np.int64)
        token_type_ids = np.zeros_like(input_ids)

        p_ids = f"{CALIB_NPY_DIR}/{i:04d}_ids.npy"
        p_mask = f"{CALIB_NPY_DIR}/{i:04d}_mask.npy"
        p_type = f"{CALIB_NPY_DIR}/{i:04d}_type.npy"
        np.save(p_ids, input_ids)
        np.save(p_mask, attention_mask)
        np.save(p_type, token_type_ids)
        lines.append(f"{p_ids} {p_mask} {p_type}")

    with open(DATASET_TXT, "w") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    tok = Tokenizer.from_file(f"{MODEL_DIR}/tokenizer.json")
    build_calibration_dataset(tok)

    rknn = RKNN(verbose=True)

    ret = rknn.config(target_platform="rk3566")
    assert ret == 0, "config failed"

    # NOTE: `inputs=` is required alongside `input_size_list=` for this model —
    # rknn-toolkit2 2.3.2 refuses a dynamic ('batch_size', 'sequence_length')
    # ONNX input shape without an explicit fixed size per named input. This is
    # the single most time-consuming thing to discover from the error message
    # alone; the fix is exactly these two extra lines.
    ret = rknn.load_onnx(
        model=ONNX_PATH,
        inputs=["input_ids", "attention_mask", "token_type_ids"],
        input_size_list=[[1, SEQ_LEN], [1, SEQ_LEN], [1, SEQ_LEN]],
    )
    assert ret == 0, "load_onnx failed"

    ret = rknn.build(do_quantization=True, dataset=DATASET_TXT)
    assert ret == 0, "build failed"

    ret = rknn.export_rknn(OUT_RKNN)
    assert ret == 0, "export failed"

    print(f"done: {OUT_RKNN}")
    rknn.release()


if __name__ == "__main__":
    main()
