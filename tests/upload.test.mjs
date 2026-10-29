import assert from "node:assert/strict";
import {stagePdf, makeUploadPayload} from "../upload.mjs";

const encoder=new TextEncoder();
const original=encoder.encode("%PDF-1.7\nMock PDF bytes\n");
class FakeFileReader {
  constructor(){this.result=null;this.error=null;this.onload=null;this.onerror=null;this.onprogress=null;}
  readAsArrayBuffer(file){
    if(file.unreadable){this.error=new Error("NotReadableError");this.onerror?.();return;}
    this.result=file.bytes.buffer.slice(file.bytes.byteOffset,file.bytes.byteOffset+file.bytes.byteLength);
    this.onprogress?.({lengthComputable:true,loaded:file.bytes.byteLength,total:file.bytes.byteLength});
    this.onload?.();
  }
}
globalThis.FileReader=FakeFileReader;
const virtualDriveFile={name:"da-drive.pdf",size:original.byteLength,bytes:original};
const progress=[];
const detached=await stagePdf(virtualDriveFile,(done,total)=>progress.push([done,total]));
assert.equal(detached.type,"application/pdf");
assert.deepEqual(new Uint8Array(await detached.arrayBuffer()),original);
assert.ok(progress.length>=1);
const payload=makeUploadPayload(detached,"da-drive.pdf","automatica",true);
assert.deepEqual(new Uint8Array(await payload.get("file").arrayBuffer()),original);
assert.equal(payload.get("file").name,"da-drive.pdf");
assert.equal(payload.get("quality"),"automatica");
assert.equal(payload.get("grayscale"),"on");
await assert.rejects(stagePdf({name:"bad",size:1,unreadable:true}),/scarica il file/i);
await assert.rejects(stagePdf({name:"fake.pdf",size:3,bytes:encoder.encode("bad")}),/non contiene un PDF valido/i);
console.log("Drive FileReader -> detached Blob -> multipart tests passed");
