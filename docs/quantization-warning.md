# Warning: default int8 quantization on this NPU can silently destroy retrieval quality

**If you convert an embedding model to RKNN int8 on this board (or likely any RK3566
board) using the default `rknn-toolkit2` calibration workflow, test retrieval quality
before trusting it.** It can look completely fine from the outside -- the model loads,
runs, returns a 384-dimensional vector for every sentence, nothing errors -- while the
vectors it returns are close to useless for finding related text.

## What we measured

Converting `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` to RKNN with
int8 quantization (`rknn-toolkit2` default w8a8 scheme, calibrated on 200 real sentences
from the target corpus -- not a synthetic or mismatched calibration set) produced a
model that is fast (17.5 sentences/s) and returns embeddings for every input without
any error, warning, or NaN. Measuring **recall@3** -- for a given sentence, does the
model return the same top-3 nearest neighbors (by cosine similarity) as the full-
precision reference model -- against that fp32 reference:

| Configuration | recall@3 |
|---|---|
| CPU, int8 (dynamic quantization, ONNX Runtime) | 0.871 |
| **NPU, int8 (`rknn-toolkit2`, w8a8, this board)** | **0.062** |
| NPU, fp16 (same conversion path, quantization off) | 0.994 |

0.062 is close to the recall a random ranking would produce over this candidate pool
(~0.02) -- in practice, this model returns close to random chapters for a real query.
**A downstream semantic search built on this int8 model would appear to work in every
manual smoke test** ("does it return *a* result without crashing?" -- yes) **while
actually returning noise.**

## Why this is dangerous specifically for this class of workload

Most guides for RK3566-class NPUs default to int8 -- it is the fastest option, the one
most tutorials benchmark, and the one the toolkit's example scripts use. For image
classification or object detection, a quality hit from int8 quantization is often small
and visible (confidence scores drop, a few extra misclassifications). For **sentence
embeddings used in semantic search, a quality collapse is invisible at the API surface**
-- every call still returns a well-formed vector -- and only shows up as "search results
seem kind of random" once a human starts checking them against expectations, by which
point it may already be in production.

## Diagnosis: this is a calibration failure, not a conversion bug

Two facts, from the same toolchain, isolate the cause:

1. **fp16 on the same NPU, same conversion code path, same input tokenization/masking,
   quantization simply turned off** (`rknn.build(do_quantization=False)`) scored
   **0.994** -- essentially perfect. If the bug were in how the conversion handles
   attention masking, padding, or the model's control-flow ops, fp16 would show it too.
   It doesn't.
2. Meanwhile, **CPU-side int8** (a different quantization method -- ONNX Runtime's
   dynamic quantization, not `rknn-toolkit2`'s calibrated w8a8) scored **0.871** on the
   same model, same task, same evaluation set -- quantization *per se* is not the
   problem; *this specific calibration scheme, as applied here*, is.

**Conclusion: the 200-sentence calibration set and/or the default w8a8 scheme in
`rknn-toolkit2` 2.3.2 is not adequate for this model's attention/softmax numeric range.**
We did not root-cause further (e.g., per-layer sensitivity analysis, per-channel
quantization, a larger or better-targeted calibration set, mixed precision on specific
layers) -- that is exactly the kind of follow-up this repository would welcome as a
contribution.

## What to do instead, today

- **Use the fp16 RKNN export for anything where retrieval correctness matters.** It is
  slower than int8 (see [`log.md`](log.md), 2026-08-10 addendum, for the exact numbers)
  but still meaningfully faster than CPU, and it preserves quality.
- **If you need int8's speed and memory footprint, do not trust the default
  calibration blind.** Measure recall@k (or an equivalent quality metric for your task)
  against a full-precision reference *before* deploying, on real data from your actual
  domain -- not the toolkit's example images/text.
- **Never report or compare an NPU int8 throughput number for an embedding/retrieval
  task without a quality metric next to it.** A throughput number alone cannot tell you
  whether the model is fast-and-correct or fast-and-broken.

## Reproducing this diagnosis

[`conversion/convert_to_rknn.py`](../conversion/convert_to_rknn.py) (int8) and
[`conversion/convert_to_rknn_fp16_diagnostic.py`](../conversion/convert_to_rknn_fp16_diagnostic.py)
(fp16, quantization disabled) produce the two models compared above.
[`bench/quality_diag.py`](../bench/quality_diag.py) computes recall@k between any two
sets of embeddings.
