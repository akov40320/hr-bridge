import hmac, hashlib, json
from datetime import datetime, timezone
import requests

secret = "040afe61cf9128b9fbe36b7543cbdc9aa8769cb9"
scope = "be7cfdb2-3e31-4099-b54b-4956a0e45fbe_2ae744e5-d33b-497f-aa0b-4666112f2779"
base = "https://hr-bridge.onrender.com"
path = f"/webhooks/amo-chats/in/{scope}"
url = base + path

method = "POST"
ctype = "application/json"

body_obj = {
    "payload": {
        "msgid": "test-msg",
        "message": {"text": "Тест"},
        "conversation": {"id": "lead:20471555", "client_id": "lead:20471555"},
        "sender": {"id": "tg:777", "name": "py-tester"},
    }
}

body = json.dumps(body_obj, ensure_ascii=False, separators=(",", ":"))

md5hex = hashlib.md5(body.encode("utf-8")).hexdigest()
date_ = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

string_to_sign = "\n".join([
    method.upper(),
    md5hex,
    ctype,
    date_,
    path
])

sig = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).hexdigest()

headers = {
    "Date": date_,
    "Content-Type": ctype,
    "Content-MD5": md5hex,
    "X-Signature": sig,
    "User-Agent": "py-amo-chats-tester/1.0",
}

print("Date:", date_)
print("Content-MD5:", md5hex)
print("X-Signature:", sig)

r = requests.post(url, headers=headers, data=body.encode("utf-8"))
print(r.status_code, r.text)
