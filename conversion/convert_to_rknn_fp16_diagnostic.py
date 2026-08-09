#!/usr/bin/env python3
"""Diagnostic: convert WITHOUT int8 quantization (fp16 on NPU) to isolate whether the
recall@3 collapse (0.051 vs 0.85 for CPU int8) measured on the int8 RKNN model is caused
by the w8a8 quantization itself, or by something else (e.g. padding/mask handling)."""
from rknn.api import RKNN

MODEL_DIR = "model"
ONNX_PATH = f"{MODEL_DIR}/model.onnx"
SEQ_LEN = 64
OUT_RKNN = "model/model_fp16_rk3566.rknn"

rknn = RKNN(verbose=False)
ret = rknn.config(target_platform="rk3566")
assert ret == 0
ret = rknn.load_onnx(
    model=ONNX_PATH,
    inputs=["input_ids", "attention_mask", "token_type_ids"],
    input_size_list=[[1, SEQ_LEN], [1, SEQ_LEN], [1, SEQ_LEN]],
)
assert ret == 0
ret = rknn.build(do_quantization=False)
assert ret == 0
ret = rknn.export_rknn(OUT_RKNN)
assert ret == 0
print(f"done: {OUT_RKNN}")
rknn.release()
