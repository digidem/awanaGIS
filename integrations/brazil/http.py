"""HTTP helpers for requests constrained to reviewed HTTPS hosts."""

import urllib.error
import urllib.request

from .policy import validate_allowlisted_url


class AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects outside the reviewed HTTPS host set."""

    def __init__(self, allowed_hosts):
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed, reason = validate_allowlisted_url(newurl, self.allowed_hosts, require_https=True)
        if not allowed:
            raise urllib.error.URLError(reason)
        return super().redirect_request(req, fp, code, msg, headers, newurl)
