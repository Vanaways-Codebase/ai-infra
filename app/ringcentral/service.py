import os
import aiohttp
import asyncio
import logging
import random, requests
from typing import Optional, Dict, Any, Union, BinaryIO
from pathlib import Path

from app.ringcentral.client import get_platform, call_ringcentral_api

logger = logging.getLogger(__name__)

# Max retry attempts for rate-limited requests
MAX_RETRIES = 3


class RingCentralRateLimitError(Exception):
    """Exception raised when RingCentral returns a rate limit error."""
    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after


async def _fetch_recording_metadata(recording_id: str) -> Dict[str, Any]:
    """Fetch recording metadata from RingCentral."""
    platform_data = get_platform()
    url = f"{platform_data['base_url']}/restapi/v1.0/account/~/recording/{recording_id}"

    response = await asyncio.to_thread(
        requests.get,
        url,
        headers=platform_data['headers']
    )

    if response.status_code != 200:
        raise Exception(f"Failed to get recording data: HTTP {response.status_code}")

    return response.json()


async def get_recording_audio_url(recording_id: str) -> str:
    """Return the authenticated audio URL for a RingCentral recording."""
    metadata = await _fetch_recording_metadata(recording_id)
    content_uri = metadata.get('contentUri')
    if not content_uri:
        raise ValueError(f"No content URI found for recording ID: {recording_id}")
    return content_uri


async def download_audio_by_id(recording_id: str, output_path: Union[str, Path]) -> Path:
    """
    Download audio file by recording ID from RingCentral.
    
    Args:
        recording_id: RingCentral recording ID
        output_path: Path where to save the audio file
    
    Returns:
        Path object pointing to the downloaded file
    """
    try:
        content_uri = await get_recording_audio_url(recording_id)
        return await download_audio_by_url(content_uri, output_path)
    except Exception as e:
        raise Exception(f"Failed to get recording data for ID {recording_id}: {str(e)}")

async def download_audio_by_url(url: str, output_path: Union[str, Path], retry_count: int = 0) -> Path:
    """
    Download audio file directly from a URL with rate limit handling.
    
    Args:
        url: URL of the audio file to download
        output_path: Path where to save the audio file
        retry_count: Current retry attempt count (used internally for recursion)
    
    Returns:
        Path object pointing to the downloaded file
        
    Raises:
        RingCentralRateLimitError: If rate limit is hit and max retries exceeded
    """
    output_path = Path(output_path)
    
    # Create directory if it doesn't exist
    os.makedirs(output_path.parent, exist_ok=True)
    
    try:
        # For RingCentral URLs that require authentication
        if 'ringcentral.com' in url.lower() or 'rcapi.com' in url.lower():
            platform_data = get_platform()
            headers = platform_data['headers']
        else:
            headers = {}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                # Handle rate limiting
                if response.status == 429:
                    # Get retry-after header or use exponential backoff
                    retry_after = int(response.headers.get('Retry-After', 0)) or (2 ** retry_count + random.uniform(0, 1))
                    
                    # Check if we've exceeded max retries
                    if retry_count >= MAX_RETRIES:
                        logger.warning(f"Rate limit exceeded for {url} after {retry_count} retries")
                        raise RingCentralRateLimitError(
                            f"RingCentral rate limit exceeded. Try again after {retry_after} seconds.", 
                            retry_after=retry_after
                        )
                    
                    logger.info(f"Rate limited by RingCentral. Retrying in {retry_after} seconds (attempt {retry_count+1}/{MAX_RETRIES})")
                    await asyncio.sleep(retry_after)
                    
                    # Try again with incremented retry count
                    return await download_audio_by_url(url, output_path, retry_count + 1)
                
                if response.status != 200:
                    raise Exception(f"Failed to download audio file: HTTP {response.status}")
                
                # Stream the content to file
                with open(output_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(8192):
                        f.write(chunk)
        
        return output_path
    
    except RingCentralRateLimitError:
        # Re-raise rate limit errors to handle them specifically
        raise
    except Exception as e:
        # Clean up partial download if it exists
        if output_path.exists():
            output_path.unlink()
        raise Exception(f"Failed to download audio file from {url}: {str(e)}")
async def download_audio(
    output_path: Union[str, Path], 
    recording_id: Optional[str] = None, 
    url: Optional[str] = None
) -> Path:
    """
    Download audio file by either recording ID or URL.
    
    Args:
        output_path: Path where to save the audio file
        recording_id: RingCentral recording ID (optional)
        url: Direct URL to audio file (optional)
    
    Returns:
        Path object pointing to the downloaded file
    
    Raises:
        ValueError: If neither recording_id nor url is provided
        RingCentralRateLimitError: If RingCentral rate limits are exceeded
    """
    if recording_id:
        return await download_audio_by_id(recording_id, output_path)
    elif url:
        return await download_audio_by_url(url, output_path)
    else:
        raise ValueError("Either recording_id or url must be provided")
