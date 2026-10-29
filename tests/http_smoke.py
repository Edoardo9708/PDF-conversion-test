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

# The automatic mode must actually run multiple MRC variants, not merely
# assign the default preset. Check the result and its metadata.
auto_body=(("--"+boundary+"\r\nContent-Disposition: form-data; name=\"file\"; filename=\"test.pdf\"\r\n"
       "Content-Type: application/pdf\r\n\r\n").encode()+raw+
      ("\r\n--"+boundary+"\r\nContent-Disposition: form-data; name=\"quality\"\r\n\r\n"
       "automatica\r\n--"+boundary+"--\r\n").encode())
auto_request=Request(base+"/jobs",data=auto_body,headers={"Content-Type":"multipart/form-data; boundary="+boundary},method="POST")
with urlopen(auto_request,timeout=15) as response:
    assert response.status==202
    auto_id=json.load(response)["id"]
deadline=time.monotonic()+150
while time.monotonic()<deadline:
    with urlopen(base+"/jobs/"+auto_id,timeout=10) as response:
        auto_state=json.load(response)
    if auto_state["state"] in ("done","error"):
        break
    time.sleep(.7)
assert auto_state["state"]=="done",auto_state
assert auto_state["selection"]["tested"]==4,auto_state
assert sum(auto_state["selection"]["selected"].values())==1,auto_state
with urlopen(base+"/jobs/"+auto_id+"/download",timeout=10) as response:
    auto_pdf=response.read()
assert auto_pdf.startswith(b"%PDF-")
print("Automatic quality selection OK:",auto_state["selection"]["selected"],len(auto_pdf))

http.shutdown()
