"""
FastAPI application for converting DICOM images to PDF via DICOMweb WADO.
"""
import base64
import logging
import os
import time
from typing import Dict, Optional, Union, Any

import httpx
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, BackgroundTasks, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .dicomweb_utils import process_dicom_wado_study
from .pdf_utils import create_pdf_from_studies

# Load environment variables
load_dotenv()

# Configure structured logging
logging.basicConfig(
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO')),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="DICOM to PDF Converter",
    description="Convert DICOM images to PDF documents via DICOMweb WADO",
    version="1.0.0"
)

@app.on_event("startup")
async def startup_event():
    """Log environment variables on startup."""
    logger.info("=" * 80)
    logger.info("🚀 DICOM to PDF Converter API - Starting Up")
    logger.info("=" * 80)
    
    # Log critical environment variables
    env_vars = {
        "DICOM_WADO_URL": os.getenv('DICOM_WADO_URL'),
        "CREATE_LOG_URL": os.getenv('CREATE_LOG_URL'),
        "API_HOST": os.getenv('API_HOST', '0.0.0.0'),
        "API_PORT": os.getenv('API_PORT', '9000'),
        "LOG_LEVEL": os.getenv('LOG_LEVEL', 'INFO'),
        "DEFAULT_MAX_WORKERS": os.getenv('DEFAULT_MAX_WORKERS', '4'),
        "MAX_ALLOWED_WORKERS": os.getenv('MAX_ALLOWED_WORKERS', '8'),
        "ALLOWED_CLIENT_IPS": os.getenv('ALLOWED_CLIENT_IPS', 'None (all IPs allowed)'),
    }
    
    logger.info("📋 Environment Configuration:")
    for key, value in env_vars.items():
        if value:
            # Mask sensitive parts of URLs
            display_value = value
            if 'URL' in key and value and len(value) > 40:
                display_value = value[:30] + "..." + value[-10:]
            logger.info(f"  ✓ {key}: {display_value}")
        else:
            logger.warning(f"  ✗ {key}: NOT SET")
    
    # Validate critical configurations
    logger.info("=" * 80)
    logger.info("🔍 Validation:")
    
    if not os.getenv('DICOM_WADO_URL'):
        logger.error("  ❌ DICOM_WADO_URL is not configured! API will not work properly.")
    else:
        logger.info("  ✅ DICOM_WADO_URL is configured")
    
    if not os.getenv('CREATE_LOG_URL'):
        logger.warning("  ⚠️  CREATE_LOG_URL is not configured - external logging disabled")
    else:
        logger.info("  ✅ CREATE_LOG_URL is configured")
    
    allowed_ips = os.getenv('ALLOWED_CLIENT_IPS', '').strip()
    if allowed_ips:
        ip_list = [ip.strip() for ip in allowed_ips.split(',') if ip.strip()]
        logger.info(f"  ✅ IP Validation enabled - {len(ip_list)} allowed IPs")
    else:
        logger.warning("  ⚠️  IP Validation disabled - all IPs allowed")
    
    logger.info("=" * 80)
    logger.info("✅ Startup completed successfully")
    logger.info("=" * 80)

class RenderRequest(BaseModel):
    """Request model for DICOM to PDF conversion via DICOMweb WADO."""
    examID: int 
    pacs_studies_iuid: str
    CodAutorizacao: str 
    CodFaturamento: str
    CodProcedimento: str
    Authorization: str
    IntegrationToken: str
    UrlCallback: str
    anonymize: bool = False
    cover_page: bool = False
    max_workers: int = 4

class RenderRequestSync(BaseModel):
    """Request model for DICOM to PDF conversion via DICOMweb WADO."""
    examID: int 
    pacs_studies_iuid: str
    IntegrationToken: str
    anonymize: Optional[bool] = False
    cover_page: Optional[bool] = False
    max_workers: Optional[int] = 4

class CallbackPayloadSantana(BaseModel):
    """Payload sent to callback URL after processing."""
    examID: int
    studyIUID: str
    ImagensPDF: str
    CodAutorizacao: str
    CodFaturamento: str
    CodProcedimento: str
    Authorization: str
    IntegrationToken: str
    
class CallbackErrorPayload(BaseModel):
    """Payload sent to callback URL in case of error."""
    examID: int
    error: Dict[str, Union[str, int]]

# In-memory tracking to prevent duplicate processing
processed_requests = set()

def send_log_callback(
    exameID: int,
    success: bool,
    message: str,
    statusCode: int,
    statusMessage: str,
    integrationToken: str,
    additional_data: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Send log callback to external API.
    
    Args:
        exameID: Exam identifier
        success: Boolean indicating if operation was successful
        message: Log message
        statusCode: HTTP status code or custom status code
        statusMessage: Status message description
        additional_data: Additional data to include in the payload
        
    Returns:
        bool: True if log was sent successfully, False otherwise
    """
    try:
        create_log_url = os.getenv('CREATE_LOG_URL')
        
        if not create_log_url:
            logger.warning("CREATE_LOG_URL not configured")
            return False
        
        payload = {
            'exameID': exameID,
            'success': success,
            'message': message,
            'statusCode': statusCode,
            'statusMessage': statusMessage
        }
        
        if additional_data:
            payload.update(additional_data)
        
        response = requests.post(
            create_log_url,
            json=payload,
            timeout=10,
            headers={'Content-Type': 'application/json', 'token': integrationToken}
        )
        
        response.raise_for_status()
        logger.info(f"Log callback sent successfully: {exameID} - success: {success}")
        return True
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send log callback: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending log callback: {str(e)}")
        return False

def validate_client_ip(request: Request) -> bool:
    """Validate client IP against allowed IPs from environment variable."""
    allowed_ips_env = os.getenv('ALLOWED_CLIENT_IPS', '')
    
    if not allowed_ips_env:
        logger.warning("⚠️ ALLOWED_CLIENT_IPS not configured - allowing all IPs")
        return True
    
    # Parse comma-separated list of allowed IPs
    allowed_ips = [ip.strip() for ip in allowed_ips_env.split(',') if ip.strip()]
    
    if not allowed_ips:
        logger.warning("⚠️ ALLOWED_CLIENT_IPS is empty - allowing all IPs")
        return True
    
    # Get client IP (handles proxy headers)
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.headers.get("X-Real-IP", "")
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"
    
    is_allowed = client_ip in allowed_ips
    
    if not is_allowed:
        logger.warning(f"🚫 Blocked request from IP {client_ip} (allowed: {', '.join(allowed_ips)})")
    else:
        logger.debug(f"✅ Allowed request from IP {client_ip}")
    
    return is_allowed

def check_ip_access(request: Request):
    """Check IP access and raise HTTP 403 if not allowed."""
    if not validate_client_ip(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Your IP address is not authorized to access this service"
        )

async def send_callback(callback_url: str, payload: CallbackPayloadSantana):
    """Send callback without retry logic."""
    try:
        # Add error information to payload if provided
        payload_dict = { "PDF": payload.ImagensPDF,
                         "CodAutorizacao": payload.CodAutorizacao,
                         "CodFaturamento": payload.CodFaturamento,
                         "CodProcedimento": payload.CodProcedimento
                        }
            
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                callback_url,
                json=payload_dict,
                headers={
                 "Content-Type": "application/json",
                 "Authorization": payload.Authorization,
                 "user-agent": "integracao.mobilemed"
                }
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Callback successful")
                send_log_callback(
                    exameID=payload.examID,
                    success=True,
                    message=response.text or "Sucesso no envio de PDF",
                    statusCode=200,
                    statusMessage="OK",
                    integrationToken=payload.IntegrationToken,
                )
                return True
            else:
                logger.warning(f"⚠️ Callback failed with status {response.status_code}")
                send_log_callback(
                    exameID=payload.examID,
                    success=False,
                    message=f"Callback failed with status {response.status_code}: {response.text}",
                    statusCode=response.status_code,
                    statusMessage=response.reason_phrase,
                    integrationToken=payload.IntegrationToken,
                )
                return False
                
    except Exception as e:
        logger.error(f"❌ Callback failed: {str(e)}")
        send_log_callback(
            exameID=payload.examID,
            success=False,
            message=f"Callback exception: {str(e)}",
            statusCode=500,
            statusMessage="Internal Server Error",
            integrationToken=payload.IntegrationToken,
        )
        return False

async def process_dicom_async(render_request: RenderRequest, callback_url: str):
    """Process DICOM study asynchronously and send callback"""
    
    # Gerar chave única usando os novos campos
    process_key = f"{render_request.examID}-{render_request.pacs_studies_iuid}"
    
    try:
        logger.info(f"🚀 Starting async DICOM processing for examID: {render_request.examID}")
        start_time = time.time()
        
        # Process DICOM files via DICOMweb WADO usando pacs_studies_iuid
        studies = process_dicom_wado_study(
            render_request.pacs_studies_iuid,  # Usar pacs_studies_iuid
            max_workers=render_request.max_workers
        )
        
        if not studies:
            raise HTTPException(
                status_code=400, 
                detail="No valid DICOM instances found in DICOMweb server"
            )
        
        # Generate PDF
        pdf_buffer = create_pdf_from_studies(
            studies, 
            cover_page=render_request.cover_page, 
            anonymize=render_request.anonymize
        )
        
        # Convert to Base64
        pdf_base64 = base64.b64encode(pdf_buffer.getvalue()).decode('utf-8')
        
        total_time = time.time() - start_time
        pdf_size = len(pdf_buffer.getvalue())
        
        logger.info(f"⏱️ Processing completed in {total_time:.2f}s")
        logger.info(f"📄 PDF size: {pdf_size:,} bytes, Base64 size: {len(pdf_base64):,} chars")
        
        # Success callback
        callback_payload = CallbackPayloadSantana(
            examID=render_request.examID,
            studyIUID=render_request.pacs_studies_iuid,
            ImagensPDF=pdf_base64,
            CodAutorizacao=render_request.CodAutorizacao,
            CodFaturamento=render_request.CodFaturamento,
            CodProcedimento=render_request.CodProcedimento,
            Authorization=render_request.Authorization,
            IntegrationToken=render_request.IntegrationToken
        )
        
        await send_callback(callback_url, callback_payload)
        
        # Send success log
        send_log_callback(
            exameID=render_request.examID,
            success=True,
            message="PDF de imagens DICOM gerado com sucesso (async), tempo de processamento: " f"{total_time:.2f}s",
            statusCode=200,
            statusMessage="OK",
            integrationToken=render_request.IntegrationToken,
            additional_data={
                "studyIUID": render_request.pacs_studies_iuid,
                "processing_time": f"{total_time:.2f}s",
                "pdf_size": pdf_size
            },
        )
        
    except Exception as e:
        logger.error(f"❌ Error processing examID {render_request.examID}: {str(e)}")
        
        # Error callback
        # Send error log to external API
        send_log_callback(
            exameID=render_request.examID,
            success=False,
            message=f"Error processing DICOM to PDF: {str(e)}",
            statusCode=500,
            statusMessage="Internal Server Error",
            integrationToken=render_request.IntegrationToken,
            additional_data={
                "studyIUID": render_request.pacs_studies_iuid,
                "error_type": type(e).__name__
            }
        )
        
        
    finally:
        # Remove from processing set
        if process_key in processed_requests:
            processed_requests.remove(process_key)

@app.get("/pdf-generator/health")
async def health_check(request: Request) -> Dict[str, Union[str, int]]:
    """Health check endpoint"""
    # Validate client IP
    check_ip_access(request)
    
    dicom_wado_url = os.getenv('DICOM_WADO_URL')
    allowed_ips_env = os.getenv('ALLOWED_CLIENT_IPS', '')
    
    # Parse allowed IPs for response
    allowed_ips = [ip.strip() for ip in allowed_ips_env.split(',') if ip.strip()] if allowed_ips_env else []
    
    return {
        "status": "ok",
        "dicom_server": "configured" if dicom_wado_url else "not_configured",
        "ip_validation": "enabled" if allowed_ips else "disabled",
        "allowed_ips_count": len(allowed_ips)
    }

@app.post("/pdf-generator/render")
async def render_dicom_to_pdf_async(
    background_tasks: BackgroundTasks,
    render_request: RenderRequest,
    request: Request,
):
    """
    Convert DICOM files to PDF via DICOMweb WADO (Async).
    Returns immediate 200 response, processes in background, sends callback.
    """
    
    # Validate IP access
    validate_client_ip(request)
    
    logger.info(f"🚀 Starting async DICOMweb PDF render for examID: {render_request.examID}")
    
    # Generate unique processing key usando os novos campos
    process_key = f"{render_request.examID}-{render_request.pacs_studies_iuid}"
    
    # Check if already processing (idempotency)
    if process_key in processed_requests:
        logger.warning(f"⚠️ Request already being processed: {process_key}")
        raise HTTPException(
            status_code=409, 
            detail=f"Request for examID {render_request.examID} is already being processed"
        )
    
    # Add to processing set
    processed_requests.add(process_key)
    
    try:
        # Get callback URL
        callback_url = render_request.UrlCallback
        if not callback_url:
            raise HTTPException(
                status_code=500, 
                detail="Callback URL not configured (UrlCallback is missing in request)"
            )
        
        # Start background processing
        background_tasks.add_task(process_dicom_async, render_request, callback_url)
        
        # Immediate response
        return {
            "status": "accepted",
            "message": "Request accepted for processing",
            "examID": render_request.examID,
            "pacs_studies_iuid": render_request.pacs_studies_iuid,
            "callback_url": callback_url
        }
        
    except Exception as e:
        # Remove from processing set on immediate error
        if process_key in processed_requests:
            processed_requests.remove(process_key)
        raise

@app.post("/pdf-generator/render/sync")
async def render_dicom_to_pdf_sync(render_request: RenderRequestSync, request: Request):
    """
    Convert DICOM files to PDF via DICOMweb WADO (Synchronous - Legacy).
    Returns PDF directly without callback.
    """
    
    # Validate IP access
    validate_client_ip(request)
    
    logger.info(f"🚀 Starting sync DICOMweb PDF render for examID: {render_request.examID}")
    start_time = time.time()
    
    try:
        # Process DICOM files via DICOMweb WADO
        studies = process_dicom_wado_study(
            render_request.pacs_studies_iuid,  # Usar pacs_studies_iuid
            max_workers=render_request.max_workers or 4
        )
        
        if not studies:
            raise HTTPException(
                status_code=400, 
                detail="No valid DICOM instances found in DICOMweb server"
            )
        
        # Generate PDF
        pdf_start = time.time()
        pdf_buffer = create_pdf_from_studies(
            studies, 
            cover_page=render_request.cover_page or False, 
            anonymize=render_request.anonymize or False
        )
        
        total_time = time.time() - start_time
        pdf_size = len(pdf_buffer.getvalue())
        
        logger.info(f"⏱️ Sync processing completed in {total_time:.2f}s")
        logger.info(f"📄 PDF size: {pdf_size:,} bytes")
        
        # Reset buffer position for streaming
        pdf_buffer.seek(0)
        
        # Send success log
        send_log_callback(
            exameID=render_request.examID,
            success=True,
            message="PDF de imagens DICOM gerado com sucesso (sync), tempo de processamento: " f"{total_time:.2f}s",
            statusCode=200,
            statusMessage="OK",
            integrationToken=render_request.IntegrationToken,
            additional_data={
                "studyIUID": render_request.pacs_studies_iuid,
                "processing_time": f"{total_time:.2f}s",
                "pdf_size": pdf_size
            },
        )
        
        return StreamingResponse(
            iter([pdf_buffer.getvalue()]),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=exam_{render_request.examID}.pdf"}
        )
        
    except Exception as e:
        # Send error log to external API
        send_log_callback(
            exameID=render_request.examID,
            success=False,
            message=f"Error processing DICOM to PDF: {str(e)}",
            statusCode=500,
            statusMessage="Internal Server Error",
            integrationToken=render_request.IntegrationToken,
            additional_data={
                "studyIUID": render_request.pacs_studies_iuid,
                "error_type": type(e).__name__
            }
        )
        
        total_time = time.time() - start_time
        logger.error(f"❌ Error processing sync request for examID {render_request.examID} after {total_time:.2f}s: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))