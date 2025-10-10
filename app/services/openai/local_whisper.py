import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any
import whisper
import torch

logger = logging.getLogger(__name__)


class LocalWhisperService:
    """Local Whisper transcription service - no rate limits!"""
    
    def __init__(self, model_name: str = "base"):
        """
        Initialize local Whisper service.
        
        Args:
            model_name: Whisper model size (tiny, base, small, medium, large)
                - tiny: Fastest, least accurate (~1GB RAM)
                - base: Fast, decent accuracy (~1GB RAM)
                - small: Good balance (~2GB RAM)
                - medium: Better accuracy (~5GB RAM)
                - large: Best accuracy (~10GB RAM)
        """
        self.model_name = model_name
        self.model = None
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Local Whisper will use device: {self._device}")
        
    def load_model(self):
        """Load the Whisper model into memory."""
        if self.model is None:
            logger.info(f"Loading Whisper model: {self.model_name}")
        
        # Load model with appropriate dtype based on device
        if self._device == "cpu":
            # Force FP32 for CPU to avoid warning
            self.model = whisper.load_model(
                self.model_name, 
                device=self._device
            )
        else:
            # Use default (FP16) for GPU
            self.model = whisper.load_model(
                self.model_name, 
                device=self._device
            )
        
        logger.info(f"✅ Whisper model loaded: {self.model_name} on {self._device}")

    
    async def transcribe(
        self,
        audio_path: Path,
        language: str = "en",
        task: str = "transcribe"
    ) -> Dict[str, Any]:
        """
        Transcribe audio file using local Whisper.
        
        Args:
            audio_path: Path to audio file
            language: Language code (en, es, fr, etc.)
            task: 'transcribe' or 'translate'
        
        Returns:
            Dictionary with transcription results
        """
        # Load model if not already loaded
        self.load_model()
        
        logger.info(f"Transcribing {audio_path.name} with local Whisper ({self.model_name})")
        
        # Run transcription in thread pool to avoid blocking
        result = await asyncio.to_thread(
            self._transcribe_sync,
            audio_path,
            language,
            task
        )
        
        logger.info(f"✅ Local transcription complete: {len(result['text'])} characters")
        return result
    
    def _transcribe_sync(
        self,
        audio_path: Path,
        language: str,
        task: str
    ) -> Dict[str, Any]:
        """Synchronous transcription function."""
        # Transcribe with word-level timestamps
        result = self.model.transcribe(
            str(audio_path),
            language=language,
            task=task,
            verbose=False,
            word_timestamps=True
        )
        
        return {
            "text": result["text"],
            "segments": result.get("segments", []),
            "language": result.get("language", language),
            "duration": result.get("duration", 0)
        }
    
    def unload_model(self):
        """Unload model from memory."""
        if self.model is not None:
            del self.model
            self.model = None
            torch.cuda.empty_cache() if torch.cuda.is_available() else None
            logger.info("Whisper model unloaded from memory")


# Global instance
local_whisper = LocalWhisperService(model_name="base")