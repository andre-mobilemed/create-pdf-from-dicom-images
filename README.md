# DICOM to PDF Converter API

API FastAPI para conversão de imagens DICOM em documentos PDF via DICOMweb WADO-RS, com processamento assíncrono e sistema de callbacks.

## 📋 Índice

- [Características](#características)
- [Arquitetura](#arquitetura)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
  - [Desenvolvimento Local](#desenvolvimento-local)
  - [Docker](#docker)
- [Configuração](#configuração)
- [Como Usar](#como-usar)
- [Endpoints da API](#endpoints-da-api)
- [Modalidades DICOM Suportadas](#modalidades-dicom-suportadas)
- [Troubleshooting](#troubleshooting)

---

## 🎯 Características

- ✅ **Processamento Assíncrono**: Resposta imediata com processamento em background
- ✅ **DICOMweb WADO-RS**: Integração com servidores PACS via protocolo padrão
- ✅ **Múltiplas Modalidades**: Suporte para CT, MR, CR, DX, US, XA, MG, etc.
- ✅ **Transfer Syntaxes**: JPEG, JPEG 2000, JPEG Lossless, RLE, etc.
- ✅ **Conversão de Cores**: YBR_FULL, YBR_FULL_422, RGB, PALETTE COLOR
- ✅ **Processamento Paralelo**: Download otimizado com thread pool
- ✅ **Sistema de Callbacks**: Notificação automática após processamento
- ✅ **Logs Externos**: Integração com API de logs para auditoria
- ✅ **Controle de Acesso**: Restrição por IP (opcional)
- ✅ **Anonimização**: Opção de remover dados do paciente
- ✅ **Capa Personalizada**: PDF com metadados do estudo

---

## 🏗️ Arquitetura

### Fluxo de Processamento

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   Cliente   │─────►│  FastAPI     │─────►│ DICOMweb    │
│             │      │  (Async)     │      │ Server      │
└─────────────┘      └──────────────┘      └─────────────┘
       ▲                    │                      │
       │                    ▼                      ▼
       │             ┌──────────────┐      ┌─────────────┐
       │             │  Background  │      │  Download   │
       │             │  Task Queue  │      │  DICOM      │
       │             └──────────────┘      └─────────────┘
       │                    │                      │
       │                    ▼                      ▼
       │             ┌──────────────┐      ┌─────────────┐
       │             │   Process    │◄─────│  Convert    │
       └─────────────│   & Create   │      │  to PIL     │
     (Callback)      │     PDF      │      │  Images     │
                     └──────────────┘      └─────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │  Send Log    │
                     │  to External │
                     │     API      │
                     └──────────────┘
```

### Componentes

- **`main.py`**: Endpoints FastAPI e lógica de negócio
- **`dicomweb_utils.py`**: Comunicação com servidor DICOMweb WADO-RS
- **`image_utils.py`**: Conversão DICOM → PIL (windowing, YBR→RGB)
- **`pdf_utils.py`**: Geração de PDF com ReportLab
- **`models.py`**: Modelos de dados (DicomStudy, DicomSeries)

---

## 📦 Requisitos

### Sistema
- **Python**: 3.12+
- **RAM**: 2GB+ (recomendado 4GB para estudos grandes)
- **CPU**: Multi-core recomendado para processamento paralelo

### Dependências Python
- FastAPI >= 0.110
- PyDICOM >= 2.4
- PyLibJPEG (JPEG/JPEG2000 support)
- NumPy >= 1.26
- Pillow >= 10
- ReportLab >= 4

---

## 🚀 Instalação

### Desenvolvimento Local

#### 1. Clone o Repositório
```bash
git clone <repository-url>
cd create_pdf_from_dicom_images
```

#### 2. Crie Ambiente Virtual
```bash
python3.12 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# ou
.venv\Scripts\activate  # Windows
```

#### 3. Instale Dependências
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### 4. Configure Variáveis de Ambiente
```bash
cp .env.example .env
nano .env  # ou seu editor preferido
```

Edite o `.env` com suas configurações:
```env
DICOM_WADO_URL='https://your-dicom-server.com/client-api/patients'
CREATE_LOG_URL='http://your-log-server:8000/exam/statusLaudo'
API_HOST=127.0.0.1
API_PORT=9000
LOG_LEVEL=INFO
ALLOWED_CLIENT_IPS=127.0.0.1,::1
```

#### 5. Execute a API
```bash
uvicorn app.main:app --host 127.0.0.1 --port 9000 --reload
```

A API estará disponível em: **http://127.0.0.1:9000**

---

### 🐳 Docker

#### Opção 1: Docker Run

##### 1. Build da Imagem
```bash
docker build -t dicom-pdf-api .
```

##### 2. Execute o Container
```bash
docker run -d \
  --name dicom-pdf-api \
  -p 9000:9000 \
  -e DICOM_WADO_URL='https://your-dicom-server.com/client-api/patients' \
  -e CREATE_LOG_URL='http://your-log-server:8000/exam/statusLaudo' \
  -e LOG_LEVEL=INFO \
  -e ALLOWED_CLIENT_IPS='192.168.1.0/24' \
  dicom-pdf-api
```

##### 3. Verifique os Logs
```bash
docker logs -f dicom-pdf-api
```

##### 4. Teste o Health Check
```bash
curl http://localhost:9000/health
```

---

#### Opção 2: Docker Compose

##### 1. Crie `docker-compose.yml`
```yaml
version: '3.8'

services:
  dicom-pdf-api:
    build: .
    container_name: dicom-pdf-api
    ports:
      - "9000:9000"
    environment:
      - DICOM_WADO_URL=${DICOM_WADO_URL}
      - CREATE_LOG_URL=${CREATE_LOG_URL}
      - API_HOST=0.0.0.0
      - API_PORT=9000
      - DEFAULT_MAX_WORKERS=4
      - MAX_ALLOWED_WORKERS=8
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      - ALLOWED_CLIENT_IPS=${ALLOWED_CLIENT_IPS}
    env_file:
      - .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '1'
          memory: 2G
```

##### 2. Inicie o Serviço
```bash
docker-compose up -d
```

##### 3. Verifique Status
```bash
docker-compose ps
docker-compose logs -f
```

##### 4. Pare o Serviço
```bash
docker-compose down
```

---

## ⚙️ Configuração

### Variáveis de Ambiente

| Variável | Descrição | Padrão | Obrigatório |
|----------|-----------|--------|-------------|
| `DICOM_WADO_URL` | URL base do servidor DICOMweb WADO-RS | - | ✅ Sim |
| `CREATE_LOG_URL` | URL da API externa de logs | - | ❌ Não |
| `API_HOST` | Host do servidor API | `0.0.0.0` | ❌ Não |
| `API_PORT` | Porta do servidor API | `9000` | ❌ Não |
| `DEFAULT_MAX_WORKERS` | Workers padrão para download paralelo | `4` | ❌ Não |
| `MAX_ALLOWED_WORKERS` | Máximo de workers permitidos | `8` | ❌ Não |
| `LOG_LEVEL` | Nível de log (DEBUG, INFO, WARNING, ERROR) | `INFO` | ❌ Não |
| `ALLOWED_CLIENT_IPS` | IPs permitidos (separados por vírgula) | (vazio = todos) | ❌ Não |

### Controle de Acesso por IP

Para restringir o acesso:
```env
# Permitir apenas IPs específicos
ALLOWED_CLIENT_IPS=192.168.1.100,192.168.1.101,10.0.0.50

# Permitir localhost
ALLOWED_CLIENT_IPS=127.0.0.1,::1

# Permitir todos (vazio ou omitido)
ALLOWED_CLIENT_IPS=
```

---

## 📖 Como Usar

### 1. Acesse a Documentação Interativa

**Swagger UI**: http://localhost:9000/docs  
**ReDoc**: http://localhost:9000/redoc

### 2. Endpoint Assíncrono (Recomendado)

```bash
curl -X POST http://localhost:9000/render \
  -H "Content-Type: application/json" \
  -d '{
    "examID": 12345,
    "pacs_studies_iuid": "1.2.840.113619.2.417.3.2831201586.467.1755630245.625",
    "CodAutorizacao": "AUTH123",
    "CodFaturamento": "FAT456",
    "CodProcedimento": "PROC789",
    "Authorization": "Bearer YOUR_TOKEN",
    "IntegrationToken": "INTEGRATION_TOKEN",
    "UrlCallback": "https://your-system.com/callback",
    "anonymize": false,
    "cover_page": true,
    "max_workers": 4
  }'
```

**Resposta Imediata** (200 OK):
```json
{
  "status": "accepted",
  "message": "Request accepted for processing",
  "examID": 12345,
  "pacs_studies_iuid": "1.2.840.113619...",
  "callback_url": "https://your-system.com/callback"
}
```

**Callback (após processamento)**:
```json
{
  "examID": 12345,
  "studyIUID": "1.2.840.113619...",
  "ImagensPDF": "base64-encoded-pdf...",
  "CodAutorizacao": "AUTH123",
  "CodFaturamento": "FAT456-i",
  "CodProcedimento": "PROC789"
}
```

### 3. Endpoint Síncrono (Legacy)

```bash
curl -X POST http://localhost:9000/render/sync \
  -H "Content-Type: application/json" \
  -d '{
    "examID": 12345,
    "pacs_studies_iuid": "1.2.840.113619...",
    "anonymize": false,
    "cover_page": true,
    "max_workers": 4
  }' \
  --output exam_12345.pdf
```

Retorna o PDF diretamente.

---

## 🔌 Endpoints da API

### `GET /health`
Health check endpoint.

**Response**:
```json
{
  "status": "ok",
  "dicom_server": "configured",
  "ip_validation": "enabled",
  "allowed_ips_count": 2
}
```

### `POST /render`
Conversão assíncrona com callback.

**Request Body**:
```json
{
  "examID": 12345,
  "pacs_studies_iuid": "1.2.840...",
  "CodAutorizacao": "string",
  "CodFaturamento": "string",
  "CodProcedimento": "string",
  "Authorization": "Bearer token",
  "IntegrationToken": "string",
  "UrlCallback": "https://...",
  "anonymize": false,
  "cover_page": true,
  "max_workers": 4
}
```

### `POST /render/sync`
Conversão síncrona (retorna PDF diretamente).

**Request Body**:
```json
{
  "examID": 12345,
  "pacs_studies_iuid": "1.2.840...",
  "anonymize": false,
  "cover_page": false,
  "max_workers": 4
}
```

**Response**: `application/pdf`

---

## 🏥 Modalidades DICOM Suportadas

| Modalidade | Nome | Photometric | Bits | Status |
|------------|------|-------------|------|--------|
| **CT** | Computed Tomography | MONOCHROME2 | 16 | ✅ |
| **MR** | Magnetic Resonance | MONOCHROME2 | 16 | ✅ |
| **CR** | Computed Radiography | MONOCHROME2 | 8/16 | ✅ |
| **DX** | Digital Radiography | MONOCHROME1/2 | 8/16 | ✅ |
| **US** | Ultrasound | RGB/YBR_FULL | 8 | ✅ |
| **XA** | X-Ray Angiography | MONOCHROME2 | 8/16 | ✅ |
| **MG** | Mammography | MONOCHROME2 | 16 | ✅ |
| **NM** | Nuclear Medicine | MONOCHROME2 | 16 | ✅ |
| **PT** | PET Scan | MONOCHROME2 | 16 | ✅ |

### Transfer Syntaxes Suportadas

- ✅ Explicit VR Little Endian
- ✅ Implicit VR Little Endian
- ✅ JPEG Baseline (Process 1)
- ✅ JPEG Extended (Process 2 & 4)
- ✅ JPEG Lossless
- ✅ JPEG 2000 Lossless
- ✅ JPEG 2000
- ✅ RLE Lossless

---

## 🐛 Troubleshooting

### Problema: Imagens Pretas no PDF

**Causa**: Handlers DICOM não configurados corretamente.

**Solução**:
```bash
# Verifique se setuptools está instalado
pip list | grep setuptools

# Se não estiver, instale
pip install setuptools

# Reinstale pylibjpeg
pip install --upgrade --force-reinstall pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg

# Teste os handlers
python -c "from app.image_utils import *; print('OK')"
```

### Problema: `RuntimeError: handlers missing dependencies`

**Causa**: PyLibJPEG não detectado.

**Solução**:
```bash
pip install setuptools pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg
```

### Problema: `Connection refused` ao DICOMweb Server

**Causa**: URL do servidor incorreta ou servidor inacessível.

**Solução**:
```bash
# Teste a conectividade
curl -v "https://your-dicom-server.com/client-api/patients?studyUID=1.2.840..."

# Verifique o .env
cat .env | grep DICOM_WADO_URL
```

### Problema: Container Docker não inicia

**Causa**: Porta 9000 já em uso.

**Solução**:
```bash
# Verifique processos na porta 9000
lsof -i :9000  # Linux/Mac
netstat -ano | findstr :9000  # Windows

# Use outra porta
docker run -p 8080:9000 dicom-pdf-api
```

### Logs Detalhados

Para debug, ative logs em nível DEBUG:

```env
LOG_LEVEL=DEBUG
```

Ou via Docker:
```bash
docker run -e LOG_LEVEL=DEBUG dicom-pdf-api
```

---

## 📊 Performance

### Benchmarks

| Estudo | Séries | Imagens | Tamanho | Tempo | Throughput |
|--------|--------|---------|---------|-------|------------|
| CT Tórax | 3 | 150 | 300MB | ~25s | 6 img/s |
| MR Crânio | 5 | 200 | 400MB | ~35s | 5.7 img/s |
| CR Tórax PA | 1 | 1 | 2MB | ~1s | - |
| US Abdome | 1 | 50 | 25MB | ~8s | 6.2 img/s |

**Hardware**: 4 CPU cores, 8GB RAM, SSD

### Otimizações

- **Workers**: Ajuste `max_workers` (padrão: 4, máximo: 8)
- **RAM**: 4GB recomendado para estudos grandes
- **Network**: Baixa latência ao servidor DICOM é crítica

---

## 📝 Licença

[Adicione sua licença aqui]

---

## 🤝 Suporte

Para dúvidas ou problemas:
- Verifique a [documentação de troubleshooting](#troubleshooting)
- Ative logs DEBUG
- Execute os testes: `python test_handlers.py`

---

## 🔄 Changelog

### v1.0.0 (2025-11-10)
- ✅ Implementação inicial
- ✅ Suporte DICOMweb WADO-RS
- ✅ Processamento assíncrono
- ✅ Sistema de callbacks
- ✅ Integração com API de logs
- ✅ Controle de acesso por IP
- ✅ Correção de conversão YBR→RGB
- ✅ Suporte completo PyLibJPEG
