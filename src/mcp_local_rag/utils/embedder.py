#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MobileBERT text embedder in pure numpy. Replaces mediapipe's TextEmbedder,
which pulled in opencv, matplotlib and sounddevice just to run one model.
"""

import threading, unicodedata, zipfile

import numpy as np

from .tflite import Interpreter

# batch rows per model call; bigger batches stop helping and just eat memory
MAX_BATCH = 32
# seq lengths get rounded up to this, which keeps the number of cached plans small
SEQ_BUCKET = 16


def _is_punct(ch: str) -> bool:
    cp = ord(ch)
    # BERT treats all non-alphanumeric ASCII as punctuation, e.g. ^ $ `
    if 33 <= cp <= 47 or 58 <= cp <= 64 or 91 <= cp <= 96 or 123 <= cp <= 126:
        return True
    return unicodedata.category(ch).startswith("P")


def _is_cjk(cp: int) -> bool:
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0x20000 <= cp <= 0x2A6DF
            or 0x2A700 <= cp <= 0x2B73F or 0x2B740 <= cp <= 0x2B81F or 0x2B820 <= cp <= 0x2CEAF
            or 0xF900 <= cp <= 0xFAFF or 0x2F800 <= cp <= 0x2FA1F)


class TextEmbedder:
    def __init__(self, path: str, l2_normalize: bool = True):
        # the vocab ships zipped inside the .tflite as model metadata
        with zipfile.ZipFile(path) as z:
            words = z.read("vocab.txt").decode("utf-8").splitlines()
        self.vocab = {w: i for i, w in enumerate(words)}
        self.l2_normalize = l2_normalize

        self.interp = Interpreter(path)
        self.input_order = self.interp.input_names
        self.seq_len = self.interp.max_seq
        self.dim = self.interp.shapes[self.interp.outputs[0]][-1]
        # one cached instance serves every tool call, and fastmcp runs sync
        # tools on worker threads. The interpreter isn't reentrant.
        self._lock = threading.Lock()

    def _basic_tokenize(self, text: str) -> list:
        # no accent stripping on purpose: mediapipe doesn't do it either, and
        # matching it keeps scores identical to the old embedder
        out = []
        for ch in text.lower():
            cp = ord(ch)
            if cp == 0 or cp == 0xFFFD:
                continue
            if unicodedata.category(ch).startswith("C") and ch not in "\t\n\r":
                continue
            if _is_cjk(cp) or _is_punct(ch):
                out.append(f" {ch} ")
            else:
                out.append(" " if ch.isspace() else ch)
        return "".join(out).split()

    def _wordpiece(self, word: str) -> list:
        if len(word) > 100:
            return ["[UNK]"]
        pieces, start = [], 0
        while start < len(word):
            end = len(word)
            while end > start:
                sub = word[start:end] if start == 0 else "##" + word[start:end]
                if sub in self.vocab:
                    break
                end -= 1
            if end == start:
                return ["[UNK]"]
            pieces.append(sub)
            start = end
        return pieces

    def tokenize(self, text: str) -> list:
        return [p for w in self._basic_tokenize(text) for p in self._wordpiece(w)]

    def embed(self, text: str) -> np.ndarray:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list) -> np.ndarray:
        toks = [["[CLS]"] + self.tokenize(t)[: self.seq_len - 2] + ["[SEP]"] for t in texts]
        out = np.zeros((len(texts), self.dim), np.float32)
        # similar lengths together, so short texts don't pay for a long one's padding
        order = sorted(range(len(texts)), key=lambda i: len(toks[i]))
        for start in range(0, len(order), MAX_BATCH):
            chunk = order[start:start + MAX_BATCH]
            longest = len(toks[chunk[-1]])
            seq = min(self.seq_len, -(-longest // SEQ_BUCKET) * SEQ_BUCKET)
            ids = np.zeros((len(chunk), seq), np.int32)
            mask = np.zeros_like(ids)
            for row, i in enumerate(chunk):
                ids[row, : len(toks[i])] = [self.vocab[t] for t in toks[i]]
                mask[row, : len(toks[i])] = 1
            feeds = {"input_word_ids": ids, "input_mask": mask, "input_type_ids": np.zeros_like(ids)}
            with self._lock:
                out[chunk] = self.interp.run(*(feeds[n] for n in self.input_order))[0]
        if self.l2_normalize and len(texts):
            out /= np.linalg.norm(out, axis=1, keepdims=True)
        return out


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
