import requests
import json

try:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    # Test Baidu as it's a major one
    response = requests.get('https://newsnow.busiyi.world/api/s?id=baidu', headers=headers, timeout=10)
    if response.status_code == 200:
        data = response.json()
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(f"Error: {response.status_code}")
except Exception as e:
    print(f"Exception: {e}")
