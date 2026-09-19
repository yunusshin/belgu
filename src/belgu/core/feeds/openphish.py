from urllib.parse import urlsplit
from belgu.core.providers.base import ResultBuilder, guarded, ensure_success, host_of


class OpenPhishProvider:
    name = 'openphish'

    @guarded
    def collect(self, target, context):
        response = context.http.get('https://openphish.com/feed.txt')
        ensure_success(response)
        result = ResultBuilder(self.name, context)
        host = host_of(target)
        for line in response.text.splitlines():
            url = line.strip()
            try:
                matching = urlsplit(url).hostname == host
            except ValueError:
                continue
            if matching:
                result.add(target, 'feed_report', response.url,
                    {'reported_url': url, 'feed_report': True, 'category': 'phishing',
                     'scope': 'exact_url' if target.kind == 'url' and target.value == url else 'domain_match'})
        return result.result()
