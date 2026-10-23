#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MobileBERT text embedder on LiteRT. Replaces mediapipe's TextEmbedder,
which pulled in opencv, matplotlib and sounddevice just to run one model.
"""

import unicodedata, zipfile

import numpy as np
from ai_edge_litert.interpreter import Interpreter


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

        self.interp = Interpreter(model_path=path)
        self.interp.allocate_tensors()
        ins = {d["name"]: d for d in self.interp.get_input_details()}
        self.ids_idx = ins["input_word_ids"]["index"]
        self.mask_idx = ins["input_mask"]["index"]
        self.type_idx = ins["input_type_ids"]["index"]
        self.seq_len = ins["input_word_ids"]["shape"][1]
        self.out_idx = self.interp.get_output_details()[0]["index"]

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
        toks = ["[CLS]"] + self.tokenize(text)[: self.seq_len - 2] + ["[SEP]"]
        ids = np.zeros((1, self.seq_len), np.int32)
        mask = np.zeros((1, self.seq_len), np.int32)
        ids[0, : len(toks)] = [self.vocab[t] for t in toks]
        mask[0, : len(toks)] = 1

        self.interp.set_tensor(self.ids_idx, ids)
        self.interp.set_tensor(self.mask_idx, mask)
        self.interp.set_tensor(self.type_idx, np.zeros_like(ids))
        self.interp.invoke()

        vec = self.interp.get_tensor(self.out_idx)[0].copy()
        if self.l2_normalize:
            vec /= np.linalg.norm(vec)
        return vec


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
