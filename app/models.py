"""
DICOM data models for organizing studies and series.
Shared classes for DICOMweb processing.
"""

import logging
from typing import Dict, List, Tuple
from pydicom import Dataset

logger = logging.getLogger(__name__)


class DicomSeries:
    """Represents a DICOM series with metadata and images."""
    
    def __init__(self, series_uid: str, series_description: str = ""):
        self.series_uid = series_uid
        self.series_description = series_description
        self.instances: List[Dataset] = []
        self.modality = ""
    
    def add_instance(self, dataset: Dataset) -> None:
        """Add a DICOM instance to the series."""
        self.instances.append(dataset)
        if not self.modality and hasattr(dataset, 'Modality'):
            self.modality = dataset.Modality
    
    def sort_instances(self) -> None:
        """Sort instances by ImagePositionPatient[2], InstanceNumber, or filename."""
        def sort_key(ds: Dataset) -> Tuple[float, int, str]:
            # Primary: ImagePositionPatient[2] (Z-coordinate)
            z_pos = 0.0
            if hasattr(ds, 'ImagePositionPatient') and ds.ImagePositionPatient:
                try:
                    z_pos = float(ds.ImagePositionPatient[2])
                except (IndexError, ValueError, TypeError):
                    pass
            
            # Secondary: InstanceNumber
            instance_num = 0
            if hasattr(ds, 'InstanceNumber'):
                try:
                    instance_num = int(ds.InstanceNumber)
                except (ValueError, TypeError):
                    pass
            
            # Tertiary: filename or object ID
            filename = getattr(ds, 'filename', str(id(ds)))
            
            return (z_pos, instance_num, filename)
        
        self.instances.sort(key=sort_key)


class DicomStudy:
    """Represents a DICOM study containing multiple series."""
    
    def __init__(self, study_uid: str):
        self.study_uid = study_uid
        self.series: Dict[str, DicomSeries] = {}
        self.patient_name = ""
        self.patient_id = ""
        self.study_date = ""
        self.accession_number = ""
        self.study_description = ""
    
    def add_instance(self, dataset: Dataset) -> None:
        """Add a DICOM instance to the appropriate series."""
        series_uid = getattr(dataset, 'SeriesInstanceUID', 'UNKNOWN')
        
        if series_uid not in self.series:
            series_description = getattr(dataset, 'SeriesDescription', '')
            self.series[series_uid] = DicomSeries(series_uid, series_description)
        
        self.series[series_uid].add_instance(dataset)
        
        # Update study-level metadata from first instance
        if not self.patient_name and hasattr(dataset, 'PatientName'):
            self.patient_name = str(dataset.PatientName)
        if not self.patient_id and hasattr(dataset, 'PatientID'):
            self.patient_id = str(dataset.PatientID)
        if not self.study_date and hasattr(dataset, 'StudyDate'):
            self.study_date = str(dataset.StudyDate)
        if not self.accession_number and hasattr(dataset, 'AccessionNumber'):
            self.accession_number = str(dataset.AccessionNumber)
        if not self.study_description and hasattr(dataset, 'StudyDescription'):
            self.study_description = str(dataset.StudyDescription)
    
    def finalize(self) -> None:
        """Sort all series instances."""
        for series in self.series.values():
            series.sort_instances()
        
        logger.debug(f"📋 Study {self.study_uid[:20]}... finalized with {len(self.series)} series")
