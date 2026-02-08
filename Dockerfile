# Kế thừa từ image gốc
FROM agent0ai/agent-zero:latest

WORKDIR /a0

# (Khuyến nghị) Pin lại bộ numpy/scipy/sklearn để tránh lỗi import kiểu scipy.special
# Nếu bạn không dùng embeddings/local models thì vẫn OK, nhưng pin để an toàn lâu dài.
RUN /opt/venv-a0/bin/pip install --no-cache-dir -U \
  "pip<25" "setuptools" "wheel" \
  "numpy<2" \
  "scipy>=1.11,<1.13" \
  "scikit-learn>=1.4,<1.6" \
  "transformers<4.50" \
  "sentence-transformers<3.0"

# Cài API server + HTTP client
RUN /opt/venv-a0/bin/pip install --no-cache-dir -U \
  fastapi uvicorn pydantic requests

# Copy API wrapper
COPY main.py /a0/main.py

# Railway sẽ route theo biến môi trường PORT (bạn đang set PORT=80)
# Không cần EXPOSE vẫn chạy, nhưng để rõ:
EXPOSE 80

# Chạy uvicorn đúng port Railway
CMD ["/bin/sh", "-lc", "/opt/venv-a0/bin/python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-80}"]
