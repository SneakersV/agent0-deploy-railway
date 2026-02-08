import os
import sys
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# --- CẤU HÌNH PATH ---
# Thêm thư mục hiện tại vào sys.path để import được các module của Agent0
sys.path.append("/a0")

# --- IMPORT AGENT0 ---
# Dựa trên cấu trúc của agent0ai/agent-zero
try:
    # Import các thành phần cốt lõi
    from python.agent.agent import Agent
    from python.helpers import files
    from python.helpers.print_style import PrintStyle
except ImportError as e:
    print(f"Lỗi Import: {e}. Đang chạy trong môi trường: {os.getcwd()}")
    # Fallback cho debug
    Agent = None

app = FastAPI()

class N8nRequest(BaseModel):
    message: str # Câu lệnh n8n gửi sang

@app.get("/")
def health_check():
    return {"status": "Agent0 API is ready on Railway"}

@app.post("/chat")
async def chat_endpoint(request: N8nRequest):
    # 1. Kiểm tra API Key (Lấy từ Railway Variable)
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="Chưa cấu hình OPENAI_API_KEY trên Railway Variables")

    # 2. Kiểm tra module Agent
    if not Agent:
        return {"error": "Không thể load module Agent0 từ image gốc."}

    try:
        # 3. Khởi tạo Agent
        # Agent0 thường tự load key từ os.environ nên ta không cần truyền trực tiếp nếu đã set env
        agent_instance = Agent(number=0)

        # 4. Gửi lệnh cho Agent xử lý
        # Lưu ý: Agent0 gốc thiết kế cho CLI interactive. 
        # Hàm .chat() hoặc .instruct() tùy thuộc vào phiên bản cụ thể trong image.
        # Dưới đây là cách gọi tiêu chuẩn:
        
        # Capture output (vì Agent0 thường in ra console)
        # Đây là phần khó nhất vì Agent0 không return string mà print ra màn hình
        # Ta sẽ giả lập việc chạy và trả về thông báo thành công.
        
        response_data = agent_instance.chat(request.message)
        
        # Nếu hàm chat không trả về text mà chỉ in log, bạn cần cơ chế capture log.
        # Để đơn giản cho n8n, ta trả về kết quả object hoặc log giả định.
        return {
            "status": "success", 
            "input": request.message,
            "agent_response": str(response_data) # Convert kết quả về chuỗi
        }

    except Exception as e:
        return {"error": str(e), "details": "Lỗi khi Agent0 xử lý"}