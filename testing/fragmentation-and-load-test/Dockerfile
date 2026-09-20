# Base image already ships torch pinned to a matching CUDA runtime --
# reinstalling it via pip would just re-download the same multi-GB wheel
# for nothing.
FROM pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the model into the image at build time, not at container
# start -- so a pod restart doesn't re-hit the Hugging Face Hub, and the
# /healthz endpoint is meaningful immediately.
ENV MODEL_NAME=sshleifer/tiny-gpt2
RUN python -c "from transformers import AutoModelForCausalLM, AutoTokenizer; \
    AutoTokenizer.from_pretrained('${MODEL_NAME}'); \
    AutoModelForCausalLM.from_pretrained('${MODEL_NAME}')"

COPY server.py .

EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
