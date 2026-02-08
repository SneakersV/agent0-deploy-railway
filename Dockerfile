# Kế thừa từ Image gốc
FROM agent0ai/agent-zero:latest

# Thiết lập thư mục làm việc
WORKDIR /a0

# --- SỬA LỖI Ở ĐÂY ---
# Thay vì gọi "pip", hãy gọi "/opt/venv-a0/bin/pip"
# Cài đặt thư viện vào đúng môi trường ảo của Agent0
RUN /opt/venv-a0/bin/pip install "numpy<2.0.0" fastapi uvicorn pydantic

# Copy file main.py (API Wrapper) của bạn vào
COPY main.py /a0/main.py

# Mở cổng 8000
EXPOSE 8000

# --- SỬA LỖI KHỞI ĐỘNG ---
# Dùng python trong môi trường ảo để chạy server
CMD ["/opt/venv-a0/bin/python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]