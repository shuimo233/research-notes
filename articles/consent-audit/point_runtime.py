"""CPU runtime for a pointwise ONNX classifier over right-padded token IDs."""
from pathlib import Path

import numpy as np
import onnxruntime as ort


def make_session(path: Path, threads=4):
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])


def validate_feeds(input_ids, attention_mask):
    if (input_ids.dtype != np.int64 or attention_mask.dtype != np.int64 or
            input_ids.ndim != 2 or input_ids.shape != attention_mask.shape or 0 in input_ids.shape):
        raise ValueError("expected two equal nonempty [batch,width] int64 arrays")
    if (np.any((attention_mask != 0) & (attention_mask != 1)) or
            not np.all(attention_mask[:, 0] == 1) or np.any(np.diff(attention_mask, axis=1) > 0)):
        raise ValueError("each attention mask must be a nonempty prefix of ones followed by zeros")


def batch_logits(session, input_ids, attention_mask):
    """Return one logits vector per example under the exported graph's singleton contract."""
    validate_feeds(input_ids, attention_mask)
    logits, = session.run(["logits"], {"input_ids": input_ids, "attention_mask": attention_mask})
    return logits
