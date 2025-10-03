import os
import time
import asyncio
import random
from typing import Optional, Dict, Any, Union
from datetime import datetime, timedelta

from ringcentral import SDK
from app.core.config import settings
import base64
import requests
import aiohttp
import urllib.parse

class RingCentralApiError(Exception):
    """Exception raised for RingCentral API errors."""
    def __init__(self, message: str, status_code: int, response_body: Any = None, retry_after: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
        self.retry_after = retry_after

# Add maximum retries constant
MAX_RETRIES = 3


_platform = None
_token_cache: Dict[str, Any] = {}
_token_expiry_time: Optional[datetime] = None
_refresh_token_expiry_time: Optional[datetime] = None


def get_token(force_refresh=False):
    """Get OAuth token from RingCentral platform with caching and auto-refresh."""
    global _token_cache, _token_expiry_time, _refresh_token_expiry_time
    
    current_time = datetime.now()
    
    # Check if we have a valid token cache that's not expired and not forced to refresh
    if not force_refresh and _token_cache and _token_expiry_time and current_time < _token_expiry_time:
        return _token_cache
    
    # Check if we can use refresh token
    if not force_refresh and _token_cache and _refresh_token_expiry_time and current_time < _refresh_token_expiry_time and 'refresh_token' in _token_cache:
        try:
            return refresh_token(_token_cache['refresh_token'])
        except Exception as e:
            print(f"Refresh token failed: {e}. Falling back to full authentication.")
    
    # Full authentication
    auth_string = f"{settings.RINGCENTRAL_CLIENT_ID}:{settings.RINGCENTRAL_CLIENT_SECRET}"
    auth_header = base64.b64encode(auth_string.encode()).decode()

    params = urllib.parse.urlencode({
        'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
        'assertion': settings.RINGCENTRAL_JWT,
    })

    response = requests.post(
        f"{settings.RINGCENTRAL_API_URL}/restapi/oauth/token",
        data=params,
        headers={
            'Authorization': f'Basic {auth_header}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
    )
    
    token_data = response.json()
    _update_token_cache(token_data)
    return _token_cache


def refresh_token(refresh_token_str):
    """Refresh the access token using a refresh token."""
    auth_string = f"{settings.RINGCENTRAL_CLIENT_ID}:{settings.RINGCENTRAL_CLIENT_SECRET}"
    auth_header = base64.b64encode(auth_string.encode()).decode()
    
    params = urllib.parse.urlencode({
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token_str,
    })
    
    response = requests.post(
        f"{settings.RINGCENTRAL_API_URL}/restapi/oauth/token",
        data=params,
        headers={
            'Authorization': f'Basic {auth_header}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
    )
    
    if response.status_code != 200:
        raise Exception(f"Failed to refresh token: {response.text}")
        
    token_data = response.json()
    _update_token_cache(token_data)
    return _token_cache


def _update_token_cache(token_data):
    """Update the token cache with new token data."""
    global _token_cache, _token_expiry_time, _refresh_token_expiry_time
    
    _token_cache = token_data
    
    # Set expiration times with a small buffer (30 seconds) to avoid edge cases
    if 'expires_in' in token_data:
        _token_expiry_time = datetime.now() + timedelta(seconds=token_data['expires_in'] - 30)
        
    if 'refresh_token_expires_in' in token_data:
        _refresh_token_expiry_time = datetime.now() + timedelta(seconds=token_data['refresh_token_expires_in'] - 30)


def get_platform():
    """Makes RingCentral API calls directly without SDK. Returns headers for API requests."""
    # Ensure we have a valid token
    token_data = get_token()
    
    # Create and return authorization headers for direct API calls
    headers = {
        'Authorization': f"Bearer {token_data['access_token']}",
        'Content-Type': 'application/json'
    }
    
    return {
        'headers': headers,
        'base_url': settings.RINGCENTRAL_API_URL,
        'token_data': token_data
    }


async def call_ringcentral_api(
    endpoint: str,
    method: str = 'GET',
    data: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    retry_count: int = 0,
    binary: bool = False,
    stream: bool = False,
    timeout: aiohttp.ClientTimeout = None,
    auth_type: str = 'bearer',  # 'bearer', 'basic', or 'jwt'
    headers: Optional[Dict[str, str]] = None  # Allow custom headers
) -> Union[Dict[str, Any], bytes, aiohttp.StreamReader]:
    """
    Global async function to call RingCentral API with centralized error handling.
    
    Args:
        endpoint: API endpoint path (without the base URL)
        method: HTTP method (GET, POST, PUT, DELETE, etc.)
        data: Request body data (will be JSON serialized)
        params: URL query parameters
        retry_count: Current retry attempt count (used internally for recursion)
        binary: If True, return raw bytes instead of parsing JSON
        stream: If True, return the response stream for streaming large responses
        timeout: Custom timeout settings for the request
        auth_type: Authentication type ('bearer', 'basic', or 'jwt')
        headers: Additional custom headers to include
        
    Returns:
        Parsed JSON response, bytes data, or stream based on parameters
        
    Raises:
        RingCentralApiError: For API errors with status code and response details
    """
    # Determine base URL and prepare default headers
    base_url = settings.RINGCENTRAL_API_URL
    
    # Start with default headers
    default_headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'TapTap-AI-Client/1.0'
    }
    
    # Handle authentication based on type
    if auth_type == 'basic':
        # Use Basic auth with client ID and secret (for token endpoints)
        auth_string = f"{settings.RINGCENTRAL_CLIENT_ID}:{settings.RINGCENTRAL_CLIENT_SECRET}"
        auth_header = base64.b64encode(auth_string.encode()).decode()
        default_headers['Authorization'] = f'Basic {auth_header}'
    elif auth_type == 'jwt':
        # Direct JWT token auth
        default_headers['Authorization'] = f'Bearer {settings.RINGCENTRAL_JWT}'
    else:
        # Default - Bearer token from platform (OAuth)
        platform_data = get_platform()
        default_headers.update(platform_data['headers'])
        base_url = platform_data['base_url']
    
    # Merge custom headers with defaults (custom headers take precedence)
    if headers:
        default_headers.update(headers)
    
    # Set specific content type for form data if needed
    if data and isinstance(data, dict) and endpoint.endswith('token'):
        default_headers['Content-Type'] = 'application/x-www-form-urlencoded'
        # Convert dict to form data for token requests
        encoded_data = urllib.parse.urlencode(data)
        data = encoded_data
    
    # Build the full URL (handle if endpoint already includes the base)
    if endpoint.startswith('http'):
        url = endpoint
    elif endpoint.startswith('/'):
        url = f"{base_url}{endpoint}"
    else:
        url = f"{base_url}/{endpoint}"
    
    # Add keep-alive header for streaming requests
    if stream:
        default_headers['Connection'] = 'keep-alive'
        default_headers['Accept'] = '*/*'  # More flexible for streaming
    
    # Use longer timeout for streaming or binary downloads
    if timeout is None:
        if stream or binary:
            # 10 minutes total, 5 minutes connection timeout, no read timeout for streams
            timeout = aiohttp.ClientTimeout(total=600, connect=300, sock_read=None)
        else:
            # Standard timeout for regular API calls
            timeout = aiohttp.ClientTimeout(total=60, connect=30)
    
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Determine if we need to send as form data or JSON
            request_kwargs = {
                'headers': default_headers,
                'params': params,
                'allow_redirects': True,
                'ssl': None  # Use default SSL settings
            }
            
            # Handle different content types
            if default_headers.get('Content-Type') == 'application/x-www-form-urlencoded' and isinstance(data, str):
                request_kwargs['data'] = data
            else:
                request_kwargs['json'] = data
                
            async with session.request(
                method=method,
                url=url,
                **request_kwargs
            ) as response:
                # Handle rate limiting (429)
                if response.status == 429:
                    retry_after = int(response.headers.get('Retry-After', 0)) or (2 ** retry_count + random.uniform(0, 1))
                    
                    # Check if we've exceeded max retries
                    if retry_count >= MAX_RETRIES:
                        raise RingCentralApiError(
                            f"Rate limit exceeded after {retry_count} retries", 
                            status_code=429,
                            retry_after=retry_after
                        )
                    
                    # Wait and retry
                    await asyncio.sleep(retry_after)
                    return await call_ringcentral_api(
                        endpoint=endpoint,
                        method=method,
                        data=data,
                        params=params,
                        retry_count=retry_count+1,
                        binary=binary,
                        stream=stream,
                        timeout=timeout,
                        auth_type=auth_type,
                        headers=headers
                    )
                
                # Handle auth errors (401)
                if response.status == 401 and auth_type == 'bearer':
                    # Only retry once for auth errors to avoid infinite loops
                    if retry_count > 0:
                        raise RingCentralApiError(
                            "Authentication failed after token refresh", 
                            status_code=401,
                            response_body=await response.text()
                        )
                    
                    # Force token refresh and retry
                    get_token(force_refresh=True)
                    return await call_ringcentral_api(
                        endpoint=endpoint,
                        method=method,
                        data=data,
                        params=params,
                        retry_count=retry_count+1,
                        binary=binary,
                        stream=stream,
                        timeout=timeout,
                        auth_type=auth_type,
                        headers=headers
                    )
                
                # Handle other errors
                if response.status < 200 or response.status >= 300:
                    raise RingCentralApiError(
                        f"API request failed with status {response.status}",
                        status_code=response.status,
                        response_body=await response.text()
                    )
                
                # Return appropriate format based on params
                if stream:
                    return response.content
                elif binary:
                    try:
                        return await response.read()
                    except (aiohttp.ClientPayloadError, aiohttp.ClientError) as e:
                        # Retry on connection issues during download
                        if retry_count < MAX_RETRIES:
                            await asyncio.sleep(1)  # Brief delay before retry
                            return await call_ringcentral_api(
                                endpoint=endpoint,
                                method=method,
                                data=data,
                                params=params,
                                retry_count=retry_count+1,
                                binary=binary,
                                stream=stream,
                                timeout=timeout,
                                auth_type=auth_type,
                                headers=headers
                            )
                        else:
                            raise RingCentralApiError(f"Connection closed while downloading: {str(e)}", status_code=0)
                else:
                    return await response.json()
                    
    except (aiohttp.ClientPayloadError, asyncio.TimeoutError) as e:
        # Handle connection closed or timeout errors specifically
        if retry_count < MAX_RETRIES:
            # Exponential backoff
            wait_time = (2 ** retry_count) + random.random()
            await asyncio.sleep(wait_time)
            return await call_ringcentral_api(
                endpoint=endpoint,
                method=method,
                data=data,
                params=params,
                retry_count=retry_count+1,
                binary=binary,
                stream=stream,
                timeout=timeout,
                auth_type=auth_type,
                headers=headers
            )
        raise RingCentralApiError(f"Connection error after {retry_count} retries: {str(e)}", status_code=0)
        
    except aiohttp.ClientError as e:
        raise RingCentralApiError(f"HTTP client error: {str(e)}", status_code=0)

# # # Initialize the token cache on module load
# try:
#     get_token()
#     print("\nRingCentral client initialized with token caching", _token_cache)
# except Exception as e:
#     print(f"\nError initializing RingCentral client: {e}")