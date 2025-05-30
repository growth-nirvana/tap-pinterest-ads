"""REST client handling, including PinterestStream base class."""
from typing import Any, Dict, Optional, Iterable, Callable
import datetime

import backoff
import requests

from memoization import cached
from singer_sdk.helpers.jsonpath import extract_jsonpath
from singer_sdk.streams import RESTStream
from singer_sdk.exceptions import FatalAPIError, RetriableAPIError

from tap_pinterest_ads.auth import PinterestAuthenticator


class PinterestStream(RESTStream):
    """pinterest stream class."""

    url_base = "https://api.pinterest.com/v5/"
    run_id = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    records_jsonpath = "$.items[*]"  # Or override `parse_response`.
    next_page_token_jsonpath = "$.bookmark"  # Or override `get_next_page_token`.

    @property
    @cached
    def authenticator(self) -> PinterestAuthenticator:
        """Return a new authenticator object."""
        return PinterestAuthenticator.create_for_stream(self)

    @property
    def http_headers(self) -> dict:
        """Return the http headers needed."""
        if not self.authenticator.is_token_valid():
            self.logger.info("token invalid")
            self.authenticator.update_access_token()
        headers = {'Accept': 'application/json'}
        headers["Authorization"] = "Bearer {token}".format(token=self.authenticator.access_token)
        return headers

    def get_next_page_token(
        self, response: requests.Response, previous_token: Optional[Any]
    ) -> Optional[Any]:
        """Return a token for identifying next page or None if no more pages."""
        if self.next_page_token_jsonpath:
            all_matches = extract_jsonpath(
                self.next_page_token_jsonpath, response.json()
            )
            first_match = next(iter(all_matches), None)
            next_page_token = first_match
        else:
            next_page_token = response.headers.get("X-Next-Page", None)

        return next_page_token

    def get_url_params(
        self, context: Optional[dict], next_page_token: Optional[Any]
    ) -> Dict[str, Any]:
        """Return a dictionary of values to be used in URL parameterization."""
        params: dict = {}
        params["page_size"] = 100
        if next_page_token:
            params["bookmark"] = next_page_token
        return params

    def parse_response(self, response: requests.Response) -> Iterable[dict]:
        """Parse the response and return an iterator of result rows."""
        for record in extract_jsonpath(self.records_jsonpath, input=response.json()):
            record["run_id"] = self.run_id
            yield record

    def validate_response(self, response: requests.Response) -> None:
        if response.status_code == 429 or 500 <= response.status_code < 600:
            msg = (
                f"{response.status_code} Server Error: "
                f"{response.reason} for path: {self.path}"
                f"\n{response.text}"
            )
            raise RetriableAPIError(msg)
        elif 400 <= response.status_code < 500:
            msg = (
                f"{response.status_code} Client Error: "
                f"{response.reason} for path: {self.path}"
                f"\n{response.text}"
            )
            raise FatalAPIError(msg)

    def request_decorator(self, func: Callable) -> Callable:
        """Instantiate a decorator for handling request failures.

        Developers may override this method to provide custom backoff or retry
        handling.

        Args:
            func: Function to decorate.

        Returns:
            A decorated method.
        """
        decorator: Callable = backoff.on_exception(
            backoff.expo,
            (RetriableAPIError,),
            max_tries=5,
            factor=5,
        )(func)
        return decorator