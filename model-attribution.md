# Model attribution and license

## Source model

**[`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)**
— 118M parameters, 384-dimensional sentence embeddings, 50+ languages including
Polish and English. Published by the [sentence-transformers](https://www.sbert.net/)
project (UKP Lab, Technical University of Darmstadt).

**License: [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)**
— permits use, modification, and redistribution of derivative works (including
format conversions such as the ONNX and RKNN export this repository builds),
provided the license text is retained and changes are stated. Both conditions
are met by this document plus the conversion script's docstring.

## ONNX export used as the conversion source

**[`Xenova/paraphrase-multilingual-MiniLM-L12-v2`](https://huggingface.co/Xenova/paraphrase-multilingual-MiniLM-L12-v2)**
— the same weights as the source model above, pre-exported to ONNX (used here
instead of running our own PyTorch → ONNX export, since the weights are
identical and Xenova's export is well-tested by the transformers.js community).
No separate license is declared on that repository; it inherits the Apache-2.0
terms of the weights it re-exports.

## What this repository adds

`convert_to_rknn.py` — the additional transformation ONNX → RKNN (int8,
quantized against a calibration set of real sentences), targeting the RK3566
NPU. This is the "changes made" required to be stated under Apache-2.0 §4(b).

## Why the converted `.rknn` file itself is not committed here

The quantized RKNN file is ~120 MB — over plain git's 100 MB per-file limit.
Rather than pull in Git LFS for a documentation-focused repository, this repo
publishes the conversion script instead: running it against the same source
ONNX file and a representative calibration set reproduces the same artifact in
a few minutes on any machine with `rknn-toolkit2` installed (cross-conversion;
does not require running on the Radxa itself — see the script's docstring).
