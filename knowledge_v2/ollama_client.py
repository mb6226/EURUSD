import requests
from .config import load_config

def _url(path):
    return load_config()["ollama_url"].rstrip("/") + path

def list_models():
    r = requests.get(_url("/api/tags"), timeout=15)
    r.raise_for_status()
    return [m.get("name", "") for m in r.json().get("models", [])]

def embed(text):
    cfg = load_config()
    # Newer Ollama endpoint; fallback to legacy endpoint for older installs.
    payload = {"model": cfg["embedding_model"], "input": text}
    r = requests.post(_url("/api/embed"), json=payload, timeout=120)
    if r.status_code == 404:
        r = requests.post(_url("/api/embeddings"),
                          json={"model": cfg["embedding_model"], "prompt": text},
                          timeout=120)
    r.raise_for_status()
    data = r.json()
    if "embeddings" in data:
        return data["embeddings"][0]
    return data["embedding"]

def generate(prompt):
    cfg = load_config()
    payload = {
        "model": cfg["chat_model"],
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": cfg["temperature"], "num_predict": 800}
    }
    r = requests.post(_url("/api/generate"), json=payload, timeout=300)
    r.raise_for_status()
    return r.json().get("response", "").strip()
