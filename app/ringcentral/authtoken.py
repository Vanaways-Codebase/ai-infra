import requests
import os

def get_ringcentral_access_token(client_id: str, jwt: str, url: str = "https://platform.ringcentral.com/restapi/oauth/token") -> str:
    """
    Retrieves a RingCentral access token using JWT authentication.
    Args:
        client_id: The RingCentral app client ID.
        jwt: The JWT assertion string.
        url: The RingCentral token endpoint (default is production).
    Returns:
        The access token string if successful, else raises an exception.
    """
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt,
        "client_id": client_id
    }
    response = requests.post(url, headers=headers, data=data)
    response.raise_for_status()
    token_json = response.json()
    return token_json.get("access_token")

# Example usage:
# client_id = os.getenv("RINGCENTRAL_CLIENT_ID")
# jwt = os.getenv("RINGCENTRAL_JWT")
# access_token = get_ringcentral_access_token(client_id, jwt)
