import sys
import os
from pathlib import Path

# Adiciona o root do backend ao sys.path para permitir importações do App.*
backend_root = str(Path(__file__).parent.parent.parent.parent.absolute())
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from fastapi import FastAPI
import uvicorn
from App.Core.Services.Services import setup_security_middleware

app = FastAPI()

# Aplica o middleware que criamos
setup_security_middleware(app)


@app.get("/test-headers")
async def test_headers():
    return {"message": "Middleware do MD70 deve injetar headers aqui"}


if __name__ == "__main__":
    print("🚀 Iniciando servidor de teste isolado PROX na porta 4098...")
    uvicorn.run(app, host="127.0.0.1", port=4098)
