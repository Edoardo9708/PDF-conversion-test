"""Integration test of the upload->status->download workflow with an invented PDF."""
from __future__ import annotations

import json
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import fitz
from server import Handler

doc=fitz.open()
page=doc.new_page(width=420, height=595)
page.insert_text((40, 90), "DOCUMENTO SINTETICO", fontsize=18)
page.insert_text((40, 125), "Dato inventato: 12,34", fontsize=12)
raw=doc.tobytes()

http=ThreadingHTTPServer(("127.0.0.1",0),Handler)
threading.Thread(target=http.serve_forever,daemon=True).start()
base="http://127.0.0.1:"+str(http.server_port)
boundary="smoketest-boundary"
body=(("--"+boundary+"\r\nContent-Disposition: form-data; name=\"file\"; filename=\"test.pdf\"\r\n"
       "Content-Type: application/pdf\r\n\r\n").encode()+raw+
      ("\r\n--"+boundary+"\r\nContent-Disposition: form-data; name=\"quality\"\r\n\r\n"
       "bilanciata\r\n--"+boundary+"--\r\n").encode())
request=Request(base+"/jobs",data=body,headers={"Content-Type":"multipart/form-data; boundary="+boundary},method="POST")
with urlopen(request,timeout=15) as response:
    assert response.status==202
    identifier=json.load(response)["id"]

deadline=time.monotonic()+120
seen_stages=[]
while time.monotonic()<deadline:
    with urlopen(base+"/jobs/"+identifier,timeout=10) as response:
        state=json.load(response)
    seen_stages.append(state["phase"])
    if state["state"] in ("done","error"):
        break
    time.sleep(.5)
assert state["state"]=="done",state
assert state["output_bytes"]>1000,state
assert state["completed"] == state["total"] and state["total"] >= 3, state
assert len(seen_stages) >= 2, seen_stages
with urlopen(base+"/jobs/"+identifier+"/download",timeout=10) as response:
    data=response.read()
assert data.startswith(b"%PDF-"),data[:30]
output=fitz.open(stream=data,filetype="pdf")
assert output.page_count==1
print("Mobile progress API OK:",len(raw),"->",len(data), "stages",len(seen_stages))
http.shutdown()
