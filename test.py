import json, hashlib, hmac, requests
from email.utils import formatdate

SECRET = "040afe61cf9128b9fbe36b7543cbdc9aa8769cb9"          # как в .env
SCOPE  = "be7cfdb2-3e31-4099-b54b-4956a0e45fbe_2ae744e5-d33b-497f-aa0b-4666112f2779"        # как в .env (после connect)
CID    = "180c274a-fa21-4989-95f3-17d807945658"   # uuid/id чата из amo

path = f"/v2/origin/custom/{SCOPE}/chats/{CID}/history"
url  = "https://amojo.amocrm.ru" + path
date = formatdate(usegmt=True)
md5  = hashlib.md5(b"").hexdigest()
sign_str = "\n".join(["GET", md5, "application/json", date, path])
sig  = hmac.new(SECRET.encode(), sign_str.encode(), hashlib.sha1).hexdigest()

r = requests.get(url, headers={
    "Date": date, "Content-Type": "application/json",
    "Content-MD5": md5, "X-Signature": sig
}, params={"limit": 20, "offset": 0})
print(r.status_code, r.text)