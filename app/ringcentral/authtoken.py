import requests
import os
import base64
def get_ringcentral_access_token(client_id:str,client_secret: str,jwt_token:str ) -> str:
    """
    Retrieves a RingCentral access token using JWT authentication.
    Args:
        client_id: The RingCentral app client ID.
        jwt: The JWT assertion string.
        url: The RingCentral token endpoint (default is production).
    Returns:
        The access token string if successful, else raises an exception.
    """
    try:
        # Create basic auth header
        credentials = f"{client_id}:{client_secret}"
        auth_header = base64.b64encode(credentials.encode()).decode()
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {auth_header}'
        }
        
        data = {
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
            'assertion': jwt_token
        }
        
        response = requests.post(
            'https://platform.ringcentral.com/restapi/oauth/token',
            headers=headers,
            data=data
        )
        response.raise_for_status()
        
        token_data = response.json()
        return token_data['access_token']
        
    except requests.RequestException as e:
        print(f"Error getting access token: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"Response: {e.response.text}")
        raise

# Example usage:
# client_id = os.getenv("RINGCENTRAL_CLIENT_ID")
# jwt = os.getenv("RINGCENTRAL_JWT")
# access_token = get_ringcentral_access_token(client_id, jwt)
