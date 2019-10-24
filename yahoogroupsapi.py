from contextlib import contextmanager
import functools
import logging
import time
import os

VERIFY_HTTPS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'yahoogroups_cert_chain.pem')

try:
    from warcio.capture_http import capture_http
    warcio_failed = False
except ImportError as e:
    warcio_failed = e

import requests  # Must be imported after capture_http


@contextmanager
def dummy_contextmanager(*kargs, **kwargs):
    yield


class YahooGroupsAPI:
    BASE_URI = "https://groups.yahoo.com/api"

    API_VERSIONS = {
            'HackGroupInfo': 'v1',  # In reality, this will get the root endpoint
            'messages': 'v1',
            'files': 'v2',
            'albums': 'v2',         # v3 is available, but changes where photos are located in json
            'database': 'v1',
            'links': 'v1',
            'statistics': 'v1',
            'polls': 'v1',
            'attachments': 'v1',
            'members': 'v1',
            'topics' : 'v1'
            }

    logger = logging.getLogger(name="YahooGroupsAPI")

    s = None
    ww = None
    http_context = dummy_contextmanager

    def __init__(self, group, cookie_jar=None):
        self.s = requests.Session()
        self.group = group

        if cookie_jar:
            self.s.cookies = cookie_jar
        self.s.headers = {'Referer': self.BASE_URI}

    def set_warc_writer(self, ww):
        if ww is not None and warcio_failed:
            self.logger.fatal("Attempting to log to warc, but warcio failed to import.")
            raise warcio_failed
        self.ww = ww
        self.http_context = capture_http

    def __getattr__(self, name):
        """
        Easy, human-readable REST stub, eg:
           yga.messages(123, 'raw')
           yga.messages(count=50)
        """
        if name not in self.API_VERSIONS:
            raise AttributeError()
        return functools.partial(self.get_json, name)

    def download_file(self, url, f=None, **args):
        with self.http_context(self.ww):
            retries = 5
            while True:
                r = self.s.get(url, stream=True, verify=VERIFY_HTTPS, **args)
                if r.status_code == 400 and retries > 0:
                    self.logger.info("Got 400 error for %s, will sleep and retry %d times", url, retries)
                    retries -= 1
                    time.sleep(5)
                    continue
                r.raise_for_status()
                break

            if f is None:
                return r.content

            for chunk in r.iter_content(chunk_size=4096):
                f.write(chunk)

    def get_json(self, target, *parts, **opts):
        """Get an arbitrary endpoint and parse as json"""
        with self.http_context(self.ww):
            uri_parts = [self.BASE_URI, self.API_VERSIONS[target], 'groups', self.group, target]
            uri_parts = uri_parts + map(str, parts)

            if target == 'HackGroupInfo':
                uri_parts[4] = ''

            uri = "/".join(uri_parts)

            r = self.s.get(uri, params=opts, verify=VERIFY_HTTPS, allow_redirects=False, timeout=15)
            try:
                r.raise_for_status()
                if r.status_code != 200:
                    raise requests.exceptions.HTTPError(response=r)
                return r.json()['ygData']
            except Exception as e:
                self.logger.debug("Exception raised on uri: %s", r.request.url)
                self.logger.debug(r.content)
                raise e
