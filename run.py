"""CiteWise V3 启动入口"""
import os
import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5328"))
    uvicorn.run("api.main:app", host="0.0.0.0", port=port)
