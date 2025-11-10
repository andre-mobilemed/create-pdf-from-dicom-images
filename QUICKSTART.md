# 🚀 Guia Rápido de Início

## Desenvolvimento Local (5 minutos)

```bash
# 1. Clone e entre no diretório
cd create_pdf_from_dicom_images

# 2. Crie ambiente virtual
python3.12 -m venv .venv
source .venv/bin/activate

# 3. Instale dependências
pip install -r requirements.txt

# 4. Configure variáveis
cp .env
nano .env  # Edite com suas configurações

# 5. Inicie a API
uvicorn app.main:app --host 127.0.0.1 --port 9000 --reload
```

✅ API disponível em: http://127.0.0.1:9000  
📚 Docs: http://127.0.0.1:9000/docs

---

## Docker (3 minutos)

```bash
# 1. Configure variáveis
cp .env
nano .env  # Edite DICOM_WADO_URL e CREATE_LOG_URL

# 2. Suba o container
docker-compose up -d

# 3. Verifique logs
docker-compose logs -f

# 4. Teste
curl http://localhost:9000/health
```

✅ Container rodando!

---

## Teste Rápido

```bash
# Health Check
curl http://localhost:9000/health

# Documentação interativa
open http://localhost:9000/docs
```

---

## Variáveis Essenciais (.env)

```env
# OBRIGATÓRIO
DICOM_WADO_URL='https://seu-servidor-dicom.com/client-api/patients'

# OPCIONAL
CREATE_LOG_URL='http://seu-servidor-log:8000/exam/statusLaudo'
LOG_LEVEL=INFO
ALLOWED_CLIENT_IPS=127.0.0.1,::1
```

---

## Comandos Úteis

### Docker
```bash
# Iniciar
docker-compose up -d

# Parar
docker-compose down

# Logs
docker-compose logs -f

# Rebuild
docker-compose up -d --build

# Status
docker-compose ps
```

### Local
```bash
# Iniciar (modo desenvolvimento)
uvicorn app.main:app --reload

# Iniciar (modo produção)
uvicorn app.main:app --host 0.0.0.0 --port 9000

# Testes
python test_handlers.py
python test_image_processing.py
```

---

## Troubleshooting Rápido

### Erro: Port 9000 already in use
```bash
# Mude a porta no .env
API_PORT=8080

# Ou no docker-compose.yml
ports:
  - "8080:9000"
```

### Erro: Missing dependencies (pylibjpeg)
```bash
pip install setuptools
pip install --upgrade pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg
```

### Erro: Connection to DICOM server
```bash
# Verifique URL no .env
echo $DICOM_WADO_URL

# Teste conectividade
curl -v "$DICOM_WADO_URL?studyUID=test"
```

---

## Próximos Passos

1. ✅ Teste com `/health`
2. ✅ Acesse documentação em `/docs`
3. ✅ Faça um request de teste
4. ✅ Verifique logs com `LOG_LEVEL=DEBUG`
5. ✅ Configure callback URL
6. ✅ Teste com DICOM real

---

**Dúvidas?** Veja o [README.md](README.md) completo
