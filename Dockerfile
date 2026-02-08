FROM agent0ai/agent-zero:latest

WORKDIR /a0

# Pin các gói để tránh lỗi SciPy/NumPy
RUN /opt/venv-a0/bin/pip install --no-cache-dir -U \
  "pip<25" "setuptools" "wheel" \
  "numpy<2" \
  "scipy>=1.11,<1.13" \
  "scikit-learn>=1.4,<1.6" \
  "transformers<4.50" \
  "sentence-transformers<3.0" \
  fastapi uvicorn pydantic

COPY main.py /a0/main.py

# Railway sẽ set PORT, nên expose không quan trọng lắm, nhưng để rõ:
EXPOSE 8000

# Listen đúng PORT của Railway
CMD ["/bin/sh","-lc","/opt/venv-a0/bin/python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-80}"]
