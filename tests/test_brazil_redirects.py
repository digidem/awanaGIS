"""Redirects must stay on reviewed HTTPS hosts."""

import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from integrations.brazil import catalog, resolver
from integrations.brazil.http import AllowlistedRedirectHandler


class RedirectTests(unittest.TestCase):
    def test_redirect_targets(self):
        handler = AllowlistedRedirectHandler({"example.org"})
        request = urllib.request.Request("https://example.org/start")
        for target in ("http://example.org/end", "https://evil.org/end", "https://example.org@evil.org/end"):
            with self.subTest(target=target), self.assertRaises(urllib.error.URLError):
                handler.redirect_request(request, None, 302, "Found", {}, target)
        result = handler.redirect_request(request, None, 302, "Found", {}, "https://example.org/end")
        self.assertEqual(result.full_url, "https://example.org/end")

    def test_both_callers_install_redirect_handler(self):
        with patch.object(urllib.request, "build_opener", side_effect=urllib.error.URLError("stop")) as build:
            resolver._maybe_live_ibge_lookup("9999998", allow_network=True)
            self.assertIsInstance(build.call_args.args[0], AllowlistedRedirectHandler)
            self.assertEqual(build.call_args.args[0].allowed_hosts, {"servicodados.ibge.gov.br"})
            catalog._PROBE_CACHE.clear()
            catalog._probe_endpoint(catalog.get_source("inpe_prodes"))
            self.assertIsInstance(build.call_args.args[0], AllowlistedRedirectHandler)
            self.assertEqual(build.call_args.args[0].allowed_hosts, catalog._ALLOWED_HOSTS)
