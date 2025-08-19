import json, hashlib, hmac, requests
SECRET="040afe61cf9128b9fbe36b7543cbdc9aa8769cb9"
url="https://hr-bridge.onrender.com/webhooks/amo-chats/in/<scope_id>"
body={"message":{"conversation":{"id":"test","client_id":"lead:123"},"message":{"type":"text","text":"ping"}}, "event_type":"new_message"}
raw=json.dumps(body, separators=(',', ':'), ensure_ascii=False).encode()
sig=hmac.new(SECRET.encode(), raw, hashlib.sha1).hexdigest()
print(requests.post(url, data=raw, headers={"X-Signature":sig,"Content-Type":"application/json"}).status_code)
