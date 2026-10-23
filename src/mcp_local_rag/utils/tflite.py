#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tiny TFLite interpreter in pure numpy. It only supports the ops the bundled
MobileBERT embedder uses, so we don't need a native runtime (and its limited
wheel coverage) to run one model.
"""

import struct
import numpy as np


# --- minimal flatbuffer reader -------------------------------------------------

class _Table:
    __slots__ = ("buf", "pos", "vt", "vtlen")

    def __init__(self, buf, pos):
        self.buf, self.pos = buf, pos
        self.vt = pos - struct.unpack_from("<i", buf, pos)[0]
        self.vtlen = struct.unpack_from("<H", buf, self.vt)[0]

    def _off(self, slot):
        o = 4 + 2 * slot
        return struct.unpack_from("<H", self.buf, self.vt + o)[0] if o < self.vtlen else 0

    def scalar(self, slot, fmt, default=0):
        o = self._off(slot)
        return struct.unpack_from("<" + fmt, self.buf, self.pos + o)[0] if o else default

    def _ind(self, slot):
        o = self._off(slot)
        if not o:
            return None
        p = self.pos + o
        return p + struct.unpack_from("<I", self.buf, p)[0]

    def table(self, slot):
        p = self._ind(slot)
        return None if p is None else _Table(self.buf, p)

    def string(self, slot):
        b = self.vector(slot, np.uint8)
        return None if b is None else b.tobytes().decode("utf-8")

    def vector(self, slot, dtype):
        p = self._ind(slot)
        if p is None:
            return None
        n = struct.unpack_from("<I", self.buf, p)[0]
        return np.frombuffer(self.buf, dtype=dtype, count=n, offset=p + 4)

    def tables(self, slot):
        p = self._ind(slot)
        if p is None:
            return []
        n = struct.unpack_from("<I", self.buf, p)[0]
        out = []
        for i in range(n):
            e = p + 4 + 4 * i
            out.append(_Table(self.buf, e + struct.unpack_from("<I", self.buf, e)[0]))
        return out


# TensorType -> numpy dtype
_DTYPES = {0: np.float32, 1: np.float16, 2: np.int32, 3: np.uint8, 4: np.int64, 6: np.bool_, 7: np.int16, 9: np.int8}

_OPS = {0: "ADD", 2: "CONCATENATION", 6: "DEQUANTIZE", 9: "FULLY_CONNECTED", 18: "MUL",
        22: "RESHAPE", 25: "SOFTMAX", 34: "PAD", 36: "GATHER", 39: "TRANSPOSE", 45: "STRIDED_SLICE",
        53: "CAST", 70: "EXPAND_DIMS", 77: "SHAPE", 81: "REDUCE_PROD", 83: "PACK", 94: "FILL",
        126: "BATCH_MATMUL"}


def _act(x, code):
    if code == 0:
        return x
    if code == 1:
        return np.maximum(x, 0, out=x if x.flags.writeable else None)
    if code == 3:
        return np.clip(x, 0, 6)
    raise NotImplementedError(f"activation {code}")


def _parse_options(name, t):
    if t is None:
        return {}
    if name in ("ADD", "MUL"):
        return {"act": t.scalar(0, "b")}
    if name == "FULLY_CONNECTED":
        return {"act": t.scalar(0, "b"), "keep_dims": bool(t.scalar(2, "B"))}
    if name == "CONCATENATION":
        return {"axis": t.scalar(0, "i"), "act": t.scalar(1, "b")}
    if name == "PACK":
        return {"axis": t.scalar(1, "i")}
    if name == "STRIDED_SLICE":
        o = {k: t.scalar(i, "i") for i, k in enumerate(("begin", "end", "ellipsis", "new_axis", "shrink"))}
        if o["ellipsis"] or o["new_axis"] or t.scalar(5, "B"):
            raise NotImplementedError("strided slice mode")
        return o
    if name == "GATHER":
        if t.scalar(1, "i"):
            raise NotImplementedError("gather batch_dims")
        return {"axis": t.scalar(0, "i")}
    if name == "REDUCE_PROD":
        return {"keep_dims": bool(t.scalar(0, "B"))}
    if name == "BATCH_MATMUL":
        return {"adj_x": bool(t.scalar(0, "B")), "adj_y": bool(t.scalar(1, "B"))}
    if name == "SOFTMAX":
        return {"beta": t.scalar(0, "f", 1.0)}
    if name == "SHAPE":
        return {"out": _DTYPES[t.scalar(0, "b", 2)]}
    if name == "RESHAPE":
        ns = t.vector(0, np.int32)
        return {"new_shape": None if ns is None else ns.copy()}
    return {}


class Interpreter:
    def __init__(self, path):
        with open(path, "rb") as f:
            buf = f.read()
        model = _Table(buf, struct.unpack_from("<I", buf, 0)[0])
        buffers = model.tables(4)
        codes = []
        for oc in model.tables(1):
            code = max(oc.scalar(0, "b"), oc.scalar(3, "i"))
            if code not in _OPS:
                raise NotImplementedError(f"op code {code}")
            codes.append(_OPS[code])
        g = model.tables(2)[0]

        self.consts, self.qparams, self.dtypes, self.shapes, self.names = {}, {}, [], [], []
        for i, t in enumerate(g.tables(0)):
            dt = _DTYPES[t.scalar(1, "b")]
            self.dtypes.append(dt)
            shape = t.vector(0, np.int32)
            shape = () if shape is None else tuple(int(s) for s in shape)
            self.shapes.append(shape)
            self.names.append(t.string(3))
            q = t.table(4)
            if q is not None:
                scale, zp = q.vector(2, np.float32), q.vector(3, np.int64)
                if scale is not None and len(scale):
                    self.qparams[i] = (float(scale[0]), int(zp[0]) if zp is not None and len(zp) else 0)
            b = buffers[t.scalar(2, "I")]
            data = b.vector(0, np.uint8)
            if data is None and b.scalar(1, "Q"):  # buffer stored past the flatbuffer
                off, size = b.scalar(1, "Q"), b.scalar(2, "Q")
                data = np.frombuffer(buf, np.uint8, size, off)
            if data is not None and len(data):
                self.consts[i] = data.view(dt).reshape(shape)

        self.inputs = [int(x) for x in g.vector(1, np.int32)]
        self.outputs = [int(x) for x in g.vector(2, np.int32)]
        self.ops = []
        for op in g.tables(3):
            name = codes[op.scalar(0, "I")]
            ins = [int(x) for x in op.vector(1, np.int32)]
            outs = [int(x) for x in op.vector(2, np.int32)]
            self.ops.append((name, ins, outs, _parse_options(name, op.table(4))))

        # FC weights dequantized once and stored transposed as float32, so each FC
        # is a plain BLAS matmul. LiteRT instead quantizes activations to int8 on
        # the fly (hybrid mode); in numpy that costs more than it saves and doesn't
        # rank results any closer to LiteRT than float does.
        self.fc_weights = {}
        for name, ins, _, _ in self.ops:
            if name == "FULLY_CONNECTED" and ins[1] not in self.fc_weights:
                w = self.consts[ins[1]]
                if w.dtype == np.int8:
                    scale, zp = self.qparams[ins[1]]
                    w = (w.astype(np.float32) - zp) * np.float32(scale)
                self.fc_weights[ins[1]] = np.ascontiguousarray(w.T, dtype=np.float32)

        self.max_seq = self.shapes[self.inputs[0]][1]
        self._seq = self.max_seq
        self._plans = {}

    # --- ops ---

    def _run_op(self, name, ins, outs, o, v):
        x = [None if i < 0 else v[i] for i in ins]
        if name == "FULLY_CONNECTED":
            a = x[0]
            w = self.fc_weights[ins[1]]
            y = a.reshape(-1, w.shape[0]) @ w
            if len(x) > 2 and x[2] is not None:
                y += x[2]
            y = _act(y, o["act"])
            if o["keep_dims"]:
                y = y.reshape(a.shape[:-1] + (w.shape[1],))
            r = y
        elif name == "ADD":
            r = _act(np.add(*self._match_seq(x[0], x[1])), o["act"])
        elif name == "MUL":
            r = _act(np.multiply(*self._match_seq(x[0], x[1])), o["act"])
        elif name == "RESHAPE":
            shape = x[1] if len(x) > 1 and x[1] is not None else o["new_shape"]
            shape = [int(s) for s in shape]
            if self._seq != self.max_seq and -1 not in shape and np.prod(shape) != x[0].size:
                shape = self._fix_seq(shape, x[0].size)
            r = x[0].reshape(shape)
        elif name == "TRANSPOSE":
            r = np.transpose(x[0], tuple(int(p) for p in x[1]))
        elif name == "BATCH_MATMUL":
            a, b = x
            if o["adj_x"]:
                a = np.swapaxes(a, -1, -2)
            if o["adj_y"]:
                b = np.swapaxes(b, -1, -2)
            r = np.matmul(a, b)
        elif name == "SOFTMAX":
            z = x[0] * o["beta"] if o["beta"] != 1.0 else x[0]
            r = z - z.max(axis=-1, keepdims=True)
            np.exp(r, out=r)
            r /= r.sum(axis=-1, keepdims=True)
        elif name == "CONCATENATION":
            r = _act(np.concatenate(x, axis=o["axis"]), o["act"])
        elif name == "STRIDED_SLICE":
            a, begin, end, strides = x
            sl = []
            for d in range(len(begin)):
                bit = 1 << d
                if o["shrink"] & bit:
                    sl.append(int(begin[d]))
                    continue
                b = None if o["begin"] & bit else int(begin[d])
                e = None if o["end"] & bit else int(end[d])
                sl.append(slice(b, e, int(strides[d])))
            r = a[tuple(sl)]
        elif name == "PAD":
            r = np.pad(x[0], [(int(p[0]), int(p[1])) for p in x[1]])
        elif name == "GATHER":
            r = np.take(x[0], x[1], axis=o["axis"])
        elif name == "DEQUANTIZE":
            if ins[0] in self.qparams:
                s, zp = self.qparams[ins[0]]
                r = (x[0].astype(np.float32) - zp) * np.float32(s)
            else:
                r = x[0].astype(np.float32)
        elif name == "EXPAND_DIMS":
            r = np.expand_dims(x[0], int(np.asarray(x[1]).reshape(-1)[0]))
        elif name == "SHAPE":
            r = np.array(x[0].shape, dtype=o["out"])
        elif name == "PACK":
            r = np.stack(x, axis=o["axis"])
        elif name == "REDUCE_PROD":
            axes = tuple(int(a) for a in np.asarray(x[1]).reshape(-1))
            r = np.prod(x[0], axis=axes, keepdims=o["keep_dims"]).astype(x[0].dtype)
        elif name == "CAST":
            r = x[0].astype(self.dtypes[outs[0]])
        elif name == "FILL":
            dims = [int(d) for d in x[0]]
            if self._seq != self.max_seq and self.max_seq in dims[1:]:
                dims = self._fix_seq(dims, None)
            r = np.full(dims, x[1])
        else:
            raise NotImplementedError(name)
        v[outs[0]] = np.asarray(r)

    def _match_seq(self, a, b):
        # constants sized for 128 positions (the position embedding table) get
        # cut to the first seq positions, which is what the padded run uses anyway
        if self._seq != self.max_seq and a.ndim == b.ndim and a.shape != b.shape:
            for d in range(a.ndim):
                if a.shape[d] == self.max_seq and b.shape[d] == self._seq:
                    a = a[(slice(None),) * d + (slice(0, self._seq),)]
                elif b.shape[d] == self.max_seq and a.shape[d] == self._seq:
                    b = b[(slice(None),) * d + (slice(0, self._seq),)]
        return a, b

    def _fix_seq(self, shape, size):
        # the graph hardcodes the 128-token sequence length in some shape
        # constants, either as 128 or folded into batch*128. Rescale the first
        # one that makes the element count work. "First" matters: MobileBERT's
        # bottleneck width is also 128 and always comes after the seq dim.
        for d in range(len(shape)):
            if shape[d] and shape[d] % self.max_seq == 0 and (d > 0 or size is not None):
                fixed = shape[:d] + [shape[d] // self.max_seq * self._seq] + shape[d + 1:]
                if size is None or np.prod(fixed) == size:
                    return fixed
        raise ValueError(f"can't fit shape {shape} to seq len {self._seq}")

    def _plan(self, shapes):
        """Run once with dummy inputs of these shapes to precompute everything that
        only depends on shapes and constants (~40% of this graph is shape math)."""
        v = dict(self.consts)
        static = set(self.consts)
        for i, s in zip(self.inputs, shapes):
            v[i] = np.zeros(s, self.dtypes[i])
        dynamic_ops = []
        for name, ins, outs, o in self.ops:
            self._run_op(name, ins, outs, o, v)
            if name == "SHAPE" or all(i < 0 or i in static for i in ins):
                static.add(outs[0])
            else:
                dynamic_ops.append((name, ins, outs, o))
        return {i: v[i] for i in static}, dynamic_ops

    @property
    def input_names(self):
        return [self.names[i] for i in self.inputs]

    def run(self, *arrays):
        # inputs in graph order. Any batch size works; seq len can be any
        # multiple of 16 up to the model's, which skips the padding work.
        self._seq = arrays[0].shape[1]
        key = tuple(a.shape for a in arrays)
        if key not in self._plans:
            self._plans[key] = self._plan(key)
        static, dynamic_ops = self._plans[key]
        v = dict(static)
        for i, a in zip(self.inputs, arrays):
            v[i] = a.astype(self.dtypes[i], copy=False)
        for name, ins, outs, o in dynamic_ops:
            self._run_op(name, ins, outs, o, v)
        return [v[i] for i in self.outputs]
