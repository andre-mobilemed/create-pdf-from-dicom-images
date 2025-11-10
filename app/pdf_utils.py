"""
PDF generation utilities for creating PDF documents from DICOM studies.
Handles cover page generation, image layout, and document structure.
"""

import logging
import time
from io import BytesIO
from typing import Dict, List, Any, Tuple
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from PIL import Image

from .models import DicomStudy, DicomSeries
from .image_utils import dicom_to_pil, get_frame_count

logger = logging.getLogger(__name__)


class NumberedCanvas:
    """Custom canvas for adding headers and footers."""
    
    def __init__(self, canvas, doc):
        self.canvas = canvas
        self.doc = doc
        self.page_info = {}
    
    def set_page_info(self, series_name: str, image_info: str, window_info: str):
        """Set information for current page."""
        self.page_info = {
            'series_name': series_name,
            'image_info': image_info,
            'window_info': window_info
        }
    
    def draw_header_footer(self):
        """Draw header and footer on the page."""
        canvas = self.canvas
        width, height = A4
        
        # Header
        if 'series_name' in self.page_info:
            canvas.setFont("Helvetica", 10)
            canvas.drawString(0.5 * inch, height - 0.5 * inch, 
                            f"Series: {self.page_info['series_name']}")
            canvas.drawRightString(width - 0.5 * inch, height - 0.5 * inch,
                                 f"Page {canvas.getPageNumber()}")
        
        # Footer
        if 'image_info' in self.page_info:
            canvas.setFont("Helvetica", 8)
            canvas.drawString(0.5 * inch, 0.5 * inch, 
                            self.page_info['image_info'])
            if 'window_info' in self.page_info:
                canvas.drawRightString(width - 0.5 * inch, 0.5 * inch,
                                     self.page_info['window_info'])


def create_cover_page(study: DicomStudy, anonymize: bool = False) -> List[Any]:
    """Create a cover page with study metadata."""
    styles = getSampleStyleSheet()
    
    # Title style
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        alignment=TA_CENTER
    )
    
    # Info style
    info_style = ParagraphStyle(
        'CustomInfo',
        parent=styles['Normal'],
        fontSize=12,
        spaceAfter=12,
        alignment=TA_LEFT
    )
    
    elements = []
    
    # Title
    elements.append(Paragraph("DICOM Study Report", title_style))
    elements.append(Spacer(1, 0.5 * inch))
    
    # Study information
    if anonymize:
        # Anonymized information
        elements.append(Paragraph("<b>Patient:</b> [ANONYMIZED]", info_style))
        elements.append(Paragraph("<b>Patient ID:</b> [ANONYMIZED]", info_style))
    else:
        # Full information
        patient_name = study.patient_name or "Unknown"
        patient_id = study.patient_id or "Unknown"
        elements.append(Paragraph(f"<b>Patient Name:</b> {patient_name}", info_style))
        elements.append(Paragraph(f"<b>Patient ID:</b> {patient_id}", info_style))
    
    # Study information (always shown)
    study_date = study.study_date or "Unknown"
    if len(study_date) == 8:  # YYYYMMDD format
        try:
            formatted_date = datetime.strptime(study_date, "%Y%m%d").strftime("%Y-%m-%d")
            study_date = formatted_date
        except ValueError:
            pass
    
    elements.append(Paragraph(f"<b>Study Date:</b> {study_date}", info_style))
    elements.append(Paragraph(f"<b>Accession Number:</b> {study.accession_number or 'Unknown'}", info_style))
    elements.append(Paragraph(f"<b>Study UID:</b> {study.study_uid}", info_style))
    
    elements.append(Spacer(1, 0.3 * inch))
    
    # Series summary
    elements.append(Paragraph("<b>Series Summary:</b>", info_style))
    elements.append(Spacer(1, 0.1 * inch))
    
    for series in study.series.values():
        modality = series.modality or "Unknown"
        description = series.series_description or "No description"
        instance_count = len(series.instances)
        
        # Count total frames
        total_frames = 0
        for instance in series.instances:
            total_frames += get_frame_count(instance)
        
        series_info = (f"• <b>{modality}</b> - {description} "
                      f"({instance_count} instances, {total_frames} images)")
        elements.append(Paragraph(series_info, info_style))
    
    elements.append(Spacer(1, 0.5 * inch))
    
    # Generation timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elements.append(Paragraph(f"<i>Generated on: {timestamp}</i>", info_style))
    
    # Page break after cover
    elements.append(PageBreak())
    
    return elements


def pil_to_reportlab_image(pil_image: Image.Image, max_width: float, max_height: float) -> RLImage:
    """Convert PIL image to ReportLab image with proper scaling."""
    # Save PIL image to BytesIO
    img_buffer = BytesIO()
    
    # Convert to RGB if necessary
    if pil_image.mode in ('RGBA', 'LA'):
        background = Image.new('RGB', pil_image.size, (255, 255, 255))
        if pil_image.mode == 'RGBA':
            background.paste(pil_image, mask=pil_image.split()[-1])
        else:
            background.paste(pil_image, mask=pil_image.split()[-1])
        pil_image = background
    elif pil_image.mode not in ('RGB', 'L'):
        pil_image = pil_image.convert('RGB')
    
    pil_image.save(img_buffer, format='JPEG', quality=90)
    img_buffer.seek(0)
    
    # Calculate scaled dimensions maintaining aspect ratio
    img_width, img_height = pil_image.size
    aspect_ratio = img_width / img_height
    
    if aspect_ratio > max_width / max_height:
        # Image is wider - limit by width
        width = max_width
        height = max_width / aspect_ratio
    else:
        # Image is taller - limit by height
        height = max_height
        width = max_height * aspect_ratio
    
    # Create ReportLab image
    rl_image = RLImage(img_buffer, width=width, height=height)
    
    return rl_image


def create_image_page(series: DicomSeries, instance_idx: int, frame_idx: int = 0) -> Tuple[List[Any], Dict[str, str]]:
    """Create a page with a single DICOM image."""
    elements = []
    
    try:
        instance = series.instances[instance_idx]
        
        # Convert DICOM to PIL
        pil_image, metadata = dicom_to_pil(instance, frame_idx)
        
        # Calculate available space (A4 with margins)
        page_width, page_height = A4
        margin = 0.75 * inch
        available_width = page_width - 2 * margin
        available_height = page_height - 2 * margin - 1 * inch  # Extra space for headers/footers
        
        # Convert to ReportLab image
        rl_image = pil_to_reportlab_image(pil_image, available_width, available_height)
        
        # Center the image
        elements.append(Spacer(1, 0.2 * inch))  # Top spacing
        elements.append(rl_image)
        
        # Add image information
        styles = getSampleStyleSheet()
        info_style = ParagraphStyle(
            'ImageInfo',
            parent=styles['Normal'],
            fontSize=8,
            spaceAfter=6,
            alignment=TA_CENTER
        )
        
        # Image details
        frame_info = ""
        total_frames = get_frame_count(instance)
        if total_frames > 1:
            frame_info = f" (Frame {frame_idx + 1}/{total_frames})"
        
        instance_info = f"Instance {instance_idx + 1}/{len(series.instances)}{frame_info}"
        
        # Window information
        window_info = ""
        if 'window_center' in metadata and 'window_width' in metadata:
            wc = metadata['window_center']
            ww = metadata['window_width']
            window_info = f"W: {ww:.0f} / L: {wc:.0f}"
        
        elements.append(Spacer(1, 0.1 * inch))
        elements.append(Paragraph(instance_info, info_style))
        if window_info:
            elements.append(Paragraph(window_info, info_style))
        
        # Store metadata for headers/footers
        page_metadata = {
            'series_name': series.series_description or f"Series {series.series_uid[:8]}...",
            'image_info': instance_info,
            'window_info': window_info
        }
        
        # Add page break
        elements.append(PageBreak())
        
        return elements, page_metadata
        
    except Exception as e:
        logger.error(f"Error creating image page: {e}")
        # Return error page
        styles = getSampleStyleSheet()
        error_style = ParagraphStyle(
            'Error',
            parent=styles['Normal'],
            fontSize=12,
            alignment=TA_CENTER
        )
        
        elements.append(Spacer(1, 2 * inch))
        elements.append(Paragraph(f"Error loading image: {str(e)}", error_style))
        elements.append(PageBreak())
        
        return elements, {'series_name': 'Error', 'image_info': 'Failed to load', 'window_info': ''}


def create_pdf_from_studies(
    studies: Dict[str, DicomStudy],
    anonymize: bool = False,
    cover_page: bool = True
) -> BytesIO:
    """
    Create a PDF document from DICOM studies.
    
    Args:
        studies: Dictionary of DicomStudy objects
        anonymize: Whether to anonymize patient information
        cover_page: Whether to include a cover page
        
    Returns:
        BytesIO buffer containing the PDF
    """
    start_time = time.time()
    logger.info(f"📄 Starting PDF creation from {len(studies)} studies")
    
    buffer = BytesIO()
    
    # Create PDF document
    setup_start = time.time()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch
    )
    setup_time = time.time() - setup_start
    logger.info(f"📋 PDF document setup completed in {setup_time:.3f}s")
    
    elements = []
    
    # Process each study
    study_processing_start = time.time()
    total_images = 0
    total_series = 0
    
    for study_idx, (study_uid, study) in enumerate(studies.items()):
        study_start = time.time()
        logger.info(f"📚 Processing study {study_idx + 1}/{len(studies)}: {study_uid[:8]}...")
        
        # Add cover page if requested
        if cover_page:
            cover_start = time.time()
            cover_elements = create_cover_page(study, anonymize)
            elements.extend(cover_elements)
            cover_time = time.time() - cover_start
            logger.info(f"📑 Cover page created in {cover_time:.3f}s")
        
        # Process each series
        series_count = len(study.series)
        total_series += series_count
        
        for series_idx, (series_uid, series) in enumerate(study.series.items()):
            series_start = time.time()
            instance_count = len(series.instances)
            
            # Process each instance
            series_images = 0
            for instance_idx, instance in enumerate(series.instances):
                # Handle multi-frame instances
                frame_count = get_frame_count(instance)
                
                for frame_idx in range(frame_count):
                    try:
                        page_elements, page_metadata = create_image_page(
                            series, instance_idx, frame_idx
                        )
                        elements.extend(page_elements)
                        series_images += 1
                        total_images += 1
                        
                    except Exception as e:
                        logger.error(f"❌ Error processing instance {instance_idx}, frame {frame_idx}: {e}")
                        continue
            
            series_time = time.time() - series_start
            logger.info(f"✅ Series completed in {series_time:.2f}s - {series_images} images processed")
        
        study_time = time.time() - study_start
        logger.info(f"🏁 Study completed in {study_time:.2f}s")
    
    study_processing_time = time.time() - study_processing_start
    logger.info(f"📚 All studies processed in {study_processing_time:.2f}s - {total_series} series, {total_images} images total")
    
    if not elements:
        # Create empty document with error message
        logger.warning("⚠️ No images could be processed - creating error document")
        styles = getSampleStyleSheet()
        error_style = ParagraphStyle(
            'Error',
            parent=styles['Heading1'],
            fontSize=18,
            alignment=TA_CENTER
        )
        elements.append(Spacer(1, 2 * inch))
        elements.append(Paragraph("No images could be processed", error_style))
    
    # Build PDF
    build_start = time.time()
    logger.info(f"🔨 Building final PDF document with {len(elements)} elements...")
    try:
        doc.build(elements)
        build_time = time.time() - build_start
        total_time = time.time() - start_time
        
        buffer_size = buffer.tell()
        logger.info(f"✅ PDF document built successfully in {build_time:.2f}s")
        logger.info(f"🎉 PDF creation completed in {total_time:.2f}s - Final size: {buffer_size:,} bytes")
        logger.info(f"📊 Performance summary: Setup: {setup_time:.3f}s, Processing: {study_processing_time:.2f}s, Building: {build_time:.2f}s")
    except Exception as e:
        logger.error(f"❌ Error building PDF: {e}")
        raise
    
    buffer.seek(0)
    return buffer
