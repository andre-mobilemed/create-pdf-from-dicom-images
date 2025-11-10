"""
Image processing utilities for DICOM to PIL conversion.
Handles windowing, rescaling, and photometric interpretations.
"""

import logging
import time
from typing import Dict, Tuple, Any

import numpy as np
from PIL import Image
import pydicom
from pydicom import Dataset
from pydicom.pixel_data_handlers.util import apply_color_lut, apply_modality_lut, apply_voi_lut

# Configure pydicom to use pylibjpeg handlers
import pydicom.config
pydicom.config.APPLY_J2K_CORRECTIONS = True

# Import and register pylibjpeg handlers
try:
    import pylibjpeg
    # Force registration of handlers
    import pydicom.pixel_data_handlers.pylibjpeg_handler
except ImportError:
    pass

logger = logging.getLogger(__name__)


def apply_rescale(pixel_array: np.ndarray, dataset: Dataset) -> np.ndarray:
    """Apply rescale slope and intercept to pixel data."""
    try:
        slope = getattr(dataset, 'RescaleSlope', 1.0)
        intercept = getattr(dataset, 'RescaleIntercept', 0.0)
        
        if slope != 1.0 or intercept != 0.0:
            pixel_array = pixel_array * float(slope) + float(intercept)
        
        return pixel_array
    except Exception as e:
        logger.warning(f"Error applying rescale: {e}")
        return pixel_array


def apply_window(pixel_array: np.ndarray, window_center: float, window_width: float) -> np.ndarray:
    """Apply window/level to pixel data."""
    try:
        # Calculate window bounds
        window_min = window_center - window_width / 2
        window_max = window_center + window_width / 2
        
        # Apply windowing
        pixel_array = np.clip(pixel_array, window_min, window_max)
        
        # Scale to 0-255
        if window_max != window_min:
            pixel_array = ((pixel_array - window_min) / (window_max - window_min) * 255)
        else:
            pixel_array = np.full_like(pixel_array, 128)
        
        return pixel_array.astype(np.uint8)
    except Exception as e:
        logger.warning(f"Error applying window: {e}")
        # Fallback: simple min-max normalization
        pixel_min, pixel_max = pixel_array.min(), pixel_array.max()
        if pixel_max != pixel_min:
            pixel_array = ((pixel_array - pixel_min) / (pixel_max - pixel_min) * 255)
        else:
            pixel_array = np.full_like(pixel_array, 128)
        return pixel_array.astype(np.uint8)


def auto_window(pixel_array: np.ndarray) -> Tuple[float, float]:
    """Automatically determine window center and width."""
    try:
        # Calculate percentiles for robust windowing
        p2, p98 = np.percentile(pixel_array, [2, 98])
        
        window_center = (p2 + p98) / 2
        window_width = p98 - p2
        
        # Ensure minimum window width
        if window_width < 1:
            window_width = max(1, pixel_array.max() - pixel_array.min())
        
        return float(window_center), float(window_width)
    except Exception:
        # Fallback to simple min-max
        pixel_min, pixel_max = pixel_array.min(), pixel_array.max()
        center = (pixel_min + pixel_max) / 2
        width = max(1, pixel_max - pixel_min)
        return float(center), float(width)


def dicom_to_pil(dataset: Dataset, frame_index: int = 0) -> Tuple[Image.Image, Dict[str, Any]]:
    """
    Convert DICOM dataset to PIL Image.
    
    Args:
        dataset: DICOM dataset
        frame_index: Frame index for multi-frame images
        
    Returns:
        Tuple of (PIL Image, metadata dict)
    """
    start_time = time.time()
    try:
        # Force decompression if needed (only if dataset has file_meta)
        if hasattr(dataset, 'file_meta'):
            try:
                dataset.decompress()
            except Exception as e:
                logger.debug(f"Decompression not needed or failed: {e}")
        
        # Get pixel array
        pixel_start = time.time()
        pixel_array = dataset.pixel_array
        pixel_time = time.time() - pixel_start
        
        # Only log pixel extraction time for very slow cases (>0.1s)
        if pixel_time > 0.1:
            logger.debug(f"⏱️ Slow pixel array extraction: {pixel_time:.3f}s, shape: {pixel_array.shape}")
        
        # Get photometric interpretation early
        photometric = getattr(dataset, 'PhotometricInterpretation', 'MONOCHROME2')
        logger.debug(f"Processing {photometric} image, shape: {pixel_array.shape}, dtype: {pixel_array.dtype}")
        
        # Handle multi-frame images
        num_frames = getattr(dataset, 'NumberOfFrames', 1)
        if num_frames > 1:
            if frame_index >= pixel_array.shape[0]:
                raise ValueError(f"Frame index {frame_index} out of range (max: {pixel_array.shape[0]-1})")
            pixel_array = pixel_array[frame_index]
            logger.debug(f"Extracted frame {frame_index}/{num_frames}, new shape: {pixel_array.shape}")
        
        # Get window parameters before processing
        window_center = None
        window_width = None
        
        if hasattr(dataset, 'WindowCenter') and hasattr(dataset, 'WindowWidth'):
            try:
                wc = dataset.WindowCenter
                ww = dataset.WindowWidth
                # Handle multiple windows (take first)
                if isinstance(wc, (list, tuple)):
                    wc = wc[0]
                if isinstance(ww, (list, tuple)):
                    ww = ww[0]
                window_center = float(wc)
                window_width = float(ww)
                logger.debug(f"Using DICOM window: C={window_center}, W={window_width}")
            except (ValueError, TypeError, IndexError) as e:
                logger.warning(f"Error reading window parameters: {e}")
        
        # Process based on photometric interpretation
        if photometric in ['MONOCHROME1', 'MONOCHROME2']:
            # Grayscale image processing
            
            # Apply rescale slope/intercept
            pixel_array = apply_rescale(pixel_array, dataset)
            
            # Auto-window if no window parameters
            if window_center is None or window_width is None:
                window_center, window_width = auto_window(pixel_array)
                logger.debug(f"Auto-calculated window: C={window_center:.1f}, W={window_width:.1f}")
            
            # Apply windowing
            pixel_array = apply_window(pixel_array, window_center, window_width)
            
            # Invert for MONOCHROME1
            if photometric == 'MONOCHROME1':
                pixel_array = 255 - pixel_array
            
            image = Image.fromarray(pixel_array, mode='L')
            
        elif photometric in ['RGB', 'YBR_FULL', 'YBR_FULL_422']:
            # Color image processing
            
            # Ensure proper shape (height, width, 3)
            if len(pixel_array.shape) != 3 or pixel_array.shape[2] != 3:
                logger.error(f"Invalid RGB shape: {pixel_array.shape}")
                raise ValueError(f"Invalid RGB image shape: {pixel_array.shape}")
            
            # Convert to uint8 if needed
            if pixel_array.dtype != np.uint8:
                logger.debug(f"Converting from {pixel_array.dtype} to uint8")
                pixel_min = pixel_array.min()
                pixel_max = pixel_array.max()
                if pixel_max > pixel_min:
                    pixel_array = ((pixel_array - pixel_min) / (pixel_max - pixel_min) * 255).astype(np.uint8)
                else:
                    pixel_array = pixel_array.astype(np.uint8)
            
            # Create PIL image
            if photometric == 'RGB':
                image = Image.fromarray(pixel_array, mode='RGB')
            else:
                # YBR to RGB conversion
                # YBR_FULL and YBR_FULL_422 need color space conversion
                logger.debug(f"Converting {photometric} to RGB")
                
                # Extract Y, Cb, Cr channels
                Y = pixel_array[:, :, 0].astype(np.float32)
                Cb = pixel_array[:, :, 1].astype(np.float32) - 128
                Cr = pixel_array[:, :, 2].astype(np.float32) - 128
                
                # Convert YCbCr to RGB
                R = Y + 1.402 * Cr
                G = Y - 0.344136 * Cb - 0.714136 * Cr
                B = Y + 1.772 * Cb
                
                # Clip and convert to uint8
                R = np.clip(R, 0, 255).astype(np.uint8)
                G = np.clip(G, 0, 255).astype(np.uint8)
                B = np.clip(B, 0, 255).astype(np.uint8)
                
                # Stack channels
                rgb_array = np.stack([R, G, B], axis=2)
                image = Image.fromarray(rgb_array, mode='RGB')
        
        elif photometric == 'PALETTE COLOR':
            # Palette color images
            logger.debug("Processing PALETTE COLOR image")
            
            # Apply color LUT
            try:
                pixel_array = apply_color_lut(pixel_array, dataset)
                
                # Convert to uint8 if needed
                if pixel_array.dtype != np.uint8:
                    pixel_min = pixel_array.min()
                    pixel_max = pixel_array.max()
                    if pixel_max > pixel_min:
                        pixel_array = ((pixel_array - pixel_min) / (pixel_max - pixel_min) * 255).astype(np.uint8)
                    else:
                        pixel_array = pixel_array.astype(np.uint8)
                
                image = Image.fromarray(pixel_array, mode='RGB')
            except Exception as e:
                logger.error(f"Error applying color LUT: {e}")
                # Fallback to grayscale
                pixel_array = apply_rescale(pixel_array, dataset)
                if window_center is None or window_width is None:
                    window_center, window_width = auto_window(pixel_array)
                pixel_array = apply_window(pixel_array, window_center, window_width)
                image = Image.fromarray(pixel_array, mode='L')
        
        else:
            logger.warning(f"Unsupported photometric interpretation: {photometric}, treating as MONOCHROME2")
            # Fallback to grayscale processing
            pixel_array = apply_rescale(pixel_array, dataset)
            if window_center is None or window_width is None:
                window_center, window_width = auto_window(pixel_array)
            pixel_array = apply_window(pixel_array, window_center, window_width)
            image = Image.fromarray(pixel_array, mode='L')
        
        # Metadata for PDF generation
        metadata = {
            'window_center': window_center,
            'window_width': window_width,
            'photometric': photometric,
            'frame_index': frame_index
        }
        
        total_time = time.time() - start_time
        
        # Only log conversion time for slow cases (>0.1s)
        if total_time > 0.1:
            logger.debug(f"⏱️ Slow DICOM to PIL conversion: {total_time:.3f}s")
        
        return image, metadata
        
    except Exception as e:
        logger.error(f"Error converting DICOM to PIL: {e}", exc_info=True)
        # Return a blank white image as fallback (not black!)
        blank_image = Image.new('L', (512, 512), 128)  # Gray instead of black
        return blank_image, {'error': str(e)}


def get_frame_count(dataset: Dataset) -> int:
    """Get the number of frames in a DICOM dataset."""
    try:
        # Check NumberOfFrames attribute first
        if hasattr(dataset, 'NumberOfFrames') and dataset.NumberOfFrames > 1:
            return int(dataset.NumberOfFrames)
        
        pixel_array = dataset.pixel_array
        if len(pixel_array.shape) > 2:
            # Check if this is a color image (last dimension is 3)
            if pixel_array.shape[-1] == 3:
                # This is a color image, not multi-frame
                return 1
            # Check if first dimension looks like frames (small number compared to image dimensions)
            elif pixel_array.shape[0] < 100 and pixel_array.shape[0] < pixel_array.shape[1]:
                return pixel_array.shape[0]
        
        return 1
    except Exception:
        return 1
