"""Optional local feed exports, independent of any original project database."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from belgu.core.providers.base import ResultBuilder, guarded, host_of, parse_time


class LocalFeedProvider:
    def __init__(self, name):
        self.name = name

    @guarded
    def collect(self, target, context):
        result = ResultBuilder(self.name, context)
        path = context.source(self.name)['file_path']
        if not path:
            return result.result('unavailable', error_code='feed_not_configured')
        file = Path(path)
        if file.stat().st_size > 20 * 1024 * 1024:
            return result.result('error', error_code='feed_file_too_large')
        payload = json.loads(file.read_text())
        rows = payload if isinstance(payload, list) else payload.get('data', payload.get('models', []))
        host = host_of(target)
        for row in rows:
            value = row.get('url') or row.get('ioc') or row.get('value', '')
            candidate = urlsplit(value).hostname if '://' in value else value
            if candidate != host:
                continue
            result.add(target, 'feed_report', f'local-feed:{self.name}',
                {'reported_value': value, 'feed_report': True,
                 'category': row.get('threat_type') or row.get('desc') or row.get('category'),
                 'source_name': self.name}, parse_time(row.get('first_seen') or row.get('date')))
        return result.result()
