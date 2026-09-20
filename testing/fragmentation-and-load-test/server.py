"""A minimal real-inference server: loads a genuinely tiny GPT-2 variant
onto the GPU and runs a real forward-pass generation per request.

This is deliberately not a synthetic busy-loop -- the point of this test
is to feed waste-detector something closer to real inference-serving GPU
behavior (variable per-request latency, real memory footprint, real
utilization spikes tied to actual compute) than a scripted matmul loop
would produce. sshleifer/tiny-gpt2 is a real, tiny (~500K-parameter),
publicly hosted model used widely for exactly this kind of test -- small
enough to load in seconds, real enough that inference on it is real GPU
work.
"""
from __future__ import annotations

import os
import time

import torch
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_NAME = os.environ.get("MODEL_NAME", "sshleifer/tiny-gpt2")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

app = FastAPI()

_tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
_model = AutoModelForCausalLM.from_pretrained(MODEL_NAME).to(DEVICE)
_model.eval()


class GenerateRequest(BaseModel):
    prompt: str = "The quick brown fox"
    max_new_tokens: int = 32


@app.get("/healthz")
def healthz():
    return {"status": "ok", "device": DEVICE, "model": MODEL_NAME}


@app.post("/generate")
def generate(req: GenerateRequest):
    start = time.monotonic()
    inputs = _tokenizer(req.prompt, return_tensors="pt").to(DEVICE)
    with torch.no_grad():
        output = _model.generate(
            **inputs,
            max_new_tokens=req.max_new_tokens,
            do_sample=True,
            pad_token_id=_tokenizer.eos_token_id,
        )
    text = _tokenizer.decode(output[0], skip_special_tokens=True)
    duration_ms = (time.monotonic() - start) * 1000
    return {"text": text, "duration_ms": round(duration_ms, 1), "device": DEVICE}
