"""
DICOMweb WADO utilities for retrieving DICOM instances via WADO-RS protocol.
Integra com API existente mantendo todas as variáveis e estrutura atual.
"""
import os
import logging
import time
import json
import urllib.request
import urllib.parse
import urllib.error
from io import BytesIO
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import pydicom
from pydicom.dataset import Dataset

from .models import DicomStudy

logger = logging.getLogger(__name__)

def get_dicom_wado_url() -> str:
    """Get DICOM WADO URL from environment with proper validation"""
    # Try multiple ways to get the URL
    url = os.getenv('DICOM_WADO_URL', '').strip()
    
    # Remove quotes if present
    url = url.strip('"\'')
    
    logger.debug(f"🔍 DICOM_WADO_URL raw value: {repr(os.getenv('DICOM_WADO_URL'))}")
    logger.debug(f"🔍 DICOM_WADO_URL cleaned: {repr(url)}")
    
    if not url:
        raise ValueError("DICOM_WADO_URL environment variable not configured or empty")
    
    return url

def get_study_metadata(study_iuid: str) -> Dict:
    """
    Busca metadados do estudo via DICOMweb WADO.
    
    Primeira requisição: GET {URL_BASE}/{studyiuid}
    Retorna JSON com estrutura de metadados DICOM
    """
    try:
        dicom_wado_url = get_dicom_wado_url()
        
        # URL para buscar metadados do estudo
        metadata_url = f"{dicom_wado_url.rstrip('/')}?studyUID={study_iuid}"
        
        logger.info(f"🌐 Fetching study metadata from: {metadata_url}")
        
        # Fazer requisição HTTP
        req = urllib.request.Request(metadata_url)
        req.add_header('Accept', 'application/json')
        req.add_header('User-Agent', 'DICOM-PDF-Converter/1.0')
        
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status == 200:
                content = response.read().decode('utf-8')
                metadata = json.loads(content)
                
                logger.info(f"✅ Successfully fetched metadata for study {study_iuid}")
                logger.debug(f"📋 Metadata keys: {list(metadata.keys())}")
                
                return metadata
            else:
                raise urllib.error.HTTPError(
                    metadata_url, response.status, 
                    f"HTTP {response.status}", response.headers, None
                )
                
    except Exception as e:
        logger.error(f"❌ Failed to fetch study metadata: {e}")
        raise

def download_dicom_instance(study_uid: str, series_uid: str, sop_uid: str) -> Optional[Dataset]:
    """
    Download de uma instância DICOM específica.
    
    URL: {URL_BASE}/?studyUID={studyuid}&seriesUID={seriesiuid}&objectUID={sopiuid}
    """
    try:
        dicom_wado_url = get_dicom_wado_url()
        
        # Parâmetros para download da instância
        params = {
            'studyUID': study_uid,
            'seriesUID': series_uid,
            'objectUID': sop_uid
        }
        
        # URL para download da instância
        instance_url = f"{dicom_wado_url.rstrip('/')}/images?{urllib.parse.urlencode(params)}"
        
        # Fazer requisição HTTP com timeout reduzido
        req = urllib.request.Request(instance_url)
        req.add_header('Accept', 'application/dicom')
        req.add_header('User-Agent', 'DICOM-PDF-Converter/1.0')
        req.add_header('Connection', 'keep-alive')  # Reutilizar conexões
        
        with urllib.request.urlopen(req, timeout=15) as response:  # Timeout reduzido de 60s para 15s
            if response.status == 200:
                dicom_data = response.read()
                
                # Converter bytes para Dataset DICOM
                dataset = pydicom.dcmread(BytesIO(dicom_data))
                
                # Log apenas para downloads grandes ou lentos
                if len(dicom_data) > 1024*1024:  # > 1MB
                    logger.debug(f"✅ Downloaded large instance {sop_uid} ({len(dicom_data)/1024/1024:.1f}MB)")
                
                return dataset
            else:
                raise urllib.error.HTTPError(
                    instance_url, response.status,
                    f"HTTP {response.status}", response.headers, None
                )
                
    except Exception as e:
        logger.warning(f"⚠️ Failed to download instance {sop_uid}: {e}")
        return None

def optimize_max_workers(total_instances: int, requested_workers: int) -> int:
    """
    Otimiza o número de workers baseado no número total de instâncias
    
    Args:
        total_instances: Número total de instâncias a baixar
        requested_workers: Número de workers solicitado
        
    Returns:
        Número otimizado de workers
    """
    if total_instances <= 2:
        return 1  # Sequencial para poucos instances
    elif total_instances <= 10:
        return min(2, requested_workers)  # Máximo 2 workers para poucos instances
    elif total_instances <= 50:
        return min(4, requested_workers)  # Máximo 4 workers para médio volume
    else:
        return min(8, requested_workers)  # Máximo 8 workers para alto volume

def process_dicom_wado_study(
    study_iuid: str, 
    max_workers: int = 4) -> Dict[str, DicomStudy]:  # Remover recursive
    """
    Processa um estudo DICOM via DICOMweb WADO.
    
    Args:
        study_iuid: UID do estudo
        max_workers: Número de threads para download paralelo
        
    Returns:
        Dict com estudos organizados: {study_uid: DicomStudy}
    """
    start_time = time.time()
    logger.info(f"🌐 Starting DICOMweb WADO processing for study: {study_iuid}")
    logger.info(f"⚙️ Using {max_workers} worker threads for parallel download")
    
    try:
        # Verificar se a URL está configurada
        dicom_wado_url = get_dicom_wado_url()
        logger.info(f"🔗 Using DICOM server: {dicom_wado_url}")
        
        # 1. Buscar metadados do estudo
        metadata_start = time.time()
        metadata = get_study_metadata(study_iuid)
        metadata_time = time.time() - metadata_start
        
        logger.info(f"📋 Metadata fetched in {metadata_time:.2f}s")
        
        # 2. Contar total de instâncias primeiro para otimizar workers
        total_instances_count = 0
        for study_data in metadata.get('studies', []):
            for series_data in study_data.get('series', []):
                total_instances_count += len(series_data.get('instances', []))
        
        # Otimizar número de workers baseado no volume
        optimized_workers = optimize_max_workers(total_instances_count, max_workers)
        if optimized_workers != max_workers:
            logger.info(f"⚙️ Optimized workers: {max_workers} → {optimized_workers} (for {total_instances_count} instances)")
            max_workers = optimized_workers
        
        # 3. Organizar dados do JSON
        studies = {}
        
        # Verificar se existe a estrutura esperada
        if 'studies' not in metadata:
            raise ValueError(f"Invalid metadata structure: missing 'studies' key. Available keys: {list(metadata.keys())}")
        
        # Processar cada estudo
        for study_data in metadata['studies']:
            study_uid = study_data.get('study_iuid')
            if not study_uid:
                logger.warning("⚠️ Study without study_iuid, skipping")
                continue
            
            # Criar objeto DicomStudy
            dicom_study = DicomStudy(study_uid)
            
            # Processar séries do estudo
            series_list = study_data.get('series', [])
            logger.info(f"📊 Processing {len(series_list)} series for study {study_uid}")
            
            for series_data in series_list:
                series_uid = series_data.get('series_iuid')
                if not series_uid:
                    logger.warning("⚠️ Series without series_iuid, skipping")
                    continue
                
                # Processar instâncias da série
                instances = series_data.get('instances', [])
                logger.info(f"📁 Series {series_uid}: {len(instances)} instances")
                
                # Download paralelo das instâncias - OTIMIZADO
                download_start = time.time()
                downloaded_instances = []
                
                # Usar paralelismo mesmo para poucos instances (mínimo 2)
                if max_workers > 1 and len(instances) >= 2:
                    # Download paralelo com batch processing
                    logger.info(f"🚀 Starting parallel download with {max_workers} workers for {len(instances)} instances")
                    
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        # Submeter downloads em batch
                        future_to_sop = {}
                        for instance_data in instances:
                            sop_uid = instance_data.get('sop_iuid')
                            if sop_uid:
                                future = executor.submit(
                                    download_dicom_instance, 
                                    study_uid, series_uid, sop_uid
                                )
                                future_to_sop[future] = sop_uid
                        
                        # Coletar resultados com progress tracking
                        completed = 0
                        
                        for future in as_completed(future_to_sop):
                            dataset = future.result()
                            completed += 1
                            
                            if dataset:
                                downloaded_instances.append(dataset)
                else:
                    # Download sequencial otimizado
                    logger.info(f"🔄 Starting sequential download for {len(instances)} instances")
                    
                    for i, instance_data in enumerate(instances):
                        sop_uid = instance_data.get('sop_iuid')
                        if sop_uid:
                            dataset = download_dicom_instance(study_uid, series_uid, sop_uid)
                            if dataset:
                                downloaded_instances.append(dataset)
                        
                download_time = time.time() - download_start
                success_count = len(downloaded_instances)
                total_count = len(instances)
                success_rate = (success_count / total_count * 100) if total_count > 0 else 0
                
                # Calcular throughput
                if download_time > 0:
                    throughput = success_count / download_time
                    logger.info(f"✅ Series {series_uid} completed: {success_count}/{total_count} instances ({success_rate:.0f}%) in {download_time:.2f}s ({throughput:.1f} inst/s)")
                else:
                    logger.info(f"✅ Series {series_uid} completed: {success_count}/{total_count} instances ({success_rate:.0f}%)")
                
                # Adicionar instâncias ao estudo usando add_instance()
                for dataset in downloaded_instances:
                    dicom_study.add_instance(dataset)
                
                if not downloaded_instances:
                    logger.warning(f"⚠️ No valid instances downloaded for series {series_uid}")
            
            # Finalizar estudo
            if dicom_study.series:
                dicom_study.finalize()
                studies[study_uid] = dicom_study
                logger.info(f"🎯 Study {study_uid} completed: {len(dicom_study.series)} series")
            else:
                logger.warning(f"⚠️ No valid series found for study {study_uid}")
        
        total_time = time.time() - start_time
        
        if studies:
            total_instances = sum(len(series.instances) for study in studies.values() for series in study.series.values())
            total_series = sum(len(study.series) for study in studies.values())
            
            # Calcular métricas de performance
            avg_throughput = total_instances / total_time if total_time > 0 else 0
            download_time = total_time - metadata_time
            
            logger.info(f"🏁 DICOMweb processing completed in {total_time:.2f}s")
            logger.info(f"📊 Performance metrics:")
            logger.info(f"   • Total: {total_instances} instances from {total_series} series")
            logger.info(f"   • Metadata: {metadata_time:.2f}s ({metadata_time/total_time*100:.1f}%)")
            logger.info(f"   • Download: {download_time:.2f}s ({download_time/total_time*100:.1f}%)")
            logger.info(f"   • Throughput: {avg_throughput:.1f} instances/sec")
            logger.info(f"   • Workers: {max_workers} parallel threads")
        else:
            logger.warning(f"⚠️ No studies processed successfully in {total_time:.2f}s")
        
        return studies
        
    except Exception as e:
        logger.error(f"❌ Error in DICOMweb WADO processing: {e}")
        raise