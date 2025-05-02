"""Pinterest Authentication."""
import base64

import requests

from singer_sdk.helpers._util import utc_now
from singer_sdk.authenticators import OAuthAuthenticator, SingletonMeta


class PinterestAuthenticator(OAuthAuthenticator, metaclass=SingletonMeta):
    """Authenticator class for Pinterest."""

    @property
    def oauth_request_body(self) -> dict:
        return {
            "scope": self.oauth_scopes,
            "client_id": self.config['client_id'],
            "client_secret": self.config['client_secret'],
            "grant_type": "refresh_token",
            "refresh_token": self.config['refresh_token']
        }

    # Can probably remove some scopes after testing
    @classmethod
    def create_for_stream(cls, stream) -> "PinterestAuthenticator":
        return cls(
            stream=stream,
            auth_endpoint="https://api.pinterest.com/v5/oauth/token",
            oauth_scopes=",".join([
                "ads:read",
                "ads:write"
            ])
        )

    def update_access_token(self) -> None:
        """Update `access_token` along with: `last_refreshed` and `expires_in`.

        Raises:
            RuntimeError: When OAuth login fails.
        """
        request_time = utc_now()
        auth_request_payload = self.oauth_request_payload
        token_response = requests.post(
            self.auth_endpoint,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": "Basic {auth}".format(
                    auth=base64.b64encode('{client_id}:{client_secret}'.format(
                        client_id=self.config['client_id'],
                        client_secret=self.config['client_secret']
                    ).encode('ascii')).decode('utf-8')
                )
            },
            data=auth_request_payload
        )
        try:
            token_response.raise_for_status()
            self.logger.info("OAuth authorization attempt was successful.")
        except Exception as ex:
            raise RuntimeError(
                f"Failed OAuth login, response was '{token_response.json()}'. {ex}"
            )
        token_json = token_response.json()
        self.access_token = token_json["access_token"]
        self.expires_in = token_json["expires_in"]
        self.last_refreshed = request_time
