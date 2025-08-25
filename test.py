import requests
url = "https://hr-bridge.onrender.com/webhooks/amo-chats/in/be7cfdb2-3e31-4099-b54b-4956a0e45fbe_2ae744e5-d33b-497f-aa0b-4666112f2779"
body = '{"ping":"pong"}'
sig  = "6832bbf3eda21c5ecf8803ee375469f074a05a2b"
r = requests.post(url, data=body.encode("utf-8"),
                  headers={"Content-Type":"application/json","X-Signature":sig})
print(r.status_code, r.text)
