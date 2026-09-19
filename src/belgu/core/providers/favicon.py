from hashlib import sha256
from belgu.domain.contracts import EntityRef
from belgu.core.providers.base import ResultBuilder, ensure_success, guarded


class FaviconProvider:
    name = 'favicon'

    @guarded
    def collect(self, target, context):
        response = context.http.get('https://' + target.value + '/favicon.ico')
        ensure_success(response)
        result = ResultBuilder(self.name, context)
        if response.body and 'text/html' not in response.headers.get('content-type', ''):
            digest = sha256(response.body).hexdigest()
            i = result.add(target, 'favicon', response.url,
                           {'favicon_sha256': digest, 'strength': 'weak'}, context.now())
            result.relate(target, EntityRef('favicon_hash', digest), 'favicon', i)
        return result.result()
