# Kế thừa từ Image gốc mà bạn muốn dùng
FROM agent0ai/agent-zero:latest

# Thiết lập thư mục làm việc (trong image gốc là /a0)
WORKDIR /a0

# 1. Sửa lỗi xung đột Numpy (như bạn đã gặp ở log trước)
# 2. Cài FastAPI và Uvicorn để tạo Web Server cho n8n gọi vào
RUN pip install "numpy<2.0.0" fastapi uvicorn pydantic

# Copy file main.py của bạn vào trong container
COPY main.py /a0/main.py

# Mở cổng (Railway sẽ map cổng này)
EXPOSE 8000

# Chạy server API thay vì chạy CLI mặc định của Agent0
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]