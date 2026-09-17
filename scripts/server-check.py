"""Run inside the deployed container. No credential values are printed."""
import json
import os
import urllib.request

base = 'http://127.0.0.1:8000'
headers = {'Authorization': 'Bearer ' + os.environ['MAINTAINER_ADMIN_TOKEN']}
for endpoint in ('/api/settings', '/api/agents', '/api/providers', '/api/dashboard', '/api/runs'):
    request = urllib.request.Request(base + endpoint, headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)
        assert response.status == 200
        if endpoint == '/api/agents':
            assert len(payload) == 5
    print(endpoint + ': OK')
with urllib.request.urlopen(urllib.request.Request(base + '/api/sandbox/test', headers=headers, method='POST'), timeout=10) as response:
    assert json.load(response)['ok']
print('Local sandbox create/write/read/cleanup: OK')
with urllib.request.urlopen(base, timeout=10) as response:
    assert b'Maintune' in response.read()
print('Frontend: OK')
