// Local-only archive navigator, progress and cancellation.
const $=id=>document.getElementById(id);
const panel=$("batchPanel"), info=$("batchInfo");
let selected="", running=false;
const size=n=>(n/1024/1024).toLocaleString("it-IT",{maximumFractionDigits:2})+" MB";
async function request(url,body){
 const options={cache:"no-store"};
 if(body!==undefined){
  options.method="POST";
  options.headers={"Content-Type":"application/json"};
  options.body=JSON.stringify(body);
 }
 const response=await fetch(url,options),result=await response.json();
 if(!response.ok)throw Error(result.error||"Errore");
 return result;
}
function say(message,error=false){
 info.textContent=message;info.style.color=error?"#b52934":"";
}
async function browse(path){
 try{
  const result=await request("/batch/browse?path="+encodeURIComponent(path));
  selected=result.path;
  $("batchPath").textContent="/archive"+(selected?"/"+selected:"");
  const holder=$("batchFolders");
  holder.replaceChildren();
  function add(name,target){
   const button=document.createElement("button");
   button.type="button";button.className="folderBtn";button.textContent=name;
   button.onclick=()=>browse(target);holder.append(button);
  }
  if(selected)add("⬆ Torna su",result.parent);
  for(const entry of result.folders)add("📁 "+entry.name,entry.path);
  if(!result.folders.length)holder.append("Nessuna sottocartella.");
  $("batchPreviewResult").hidden=true;$("batchStart").disabled=true;
  say("Scegli la cartella da elaborare, poi premi Analizza.");
 }catch(error){say(error.message,true)}
}
async function preview(){
 try{
  say("Controllo le sottocartelle...");
  const p=await request("/batch/preview?path="+encodeURIComponent(selected));
  $("batchPreviewResult").hidden=false;
  $("batchCount").textContent=p.count.toLocaleString("it-IT");
  $("batchBytes").textContent=size(p.bytes);
  $("batchExamples").textContent=p.examples.join("\n")||"Nessun PDF";
  $("batchStart").disabled=!p.count||!$("batchBackup").checked||running;
  say(p.count+" PDF trovati. Le scansioni idonee saranno elaborate una alla volta.");
 }catch(error){say(error.message,true)}
}
function render(j){
 if(j.state==="idle")return;
 running=["queued","running"].includes(j.state);
 $("batchStatus").hidden=false;
 $("batchProgress").max=Math.max(1,j.total);
 $("batchProgress").value=j.done;
 $("batchNumbers").textContent=j.done+" / "+j.total+" · Convertiti "+j.converted+" · Saltati "+j.skipped+" · Errori "+j.failed+" · Risparmiati "+size(j.saved_bytes);
 $("batchCurrent").textContent=j.phase+(j.file?" · "+j.file:"");
 $("batchRecent").textContent=(j.recent||[]).slice(-8).map(x=>x.file+" · "+x.result+(x.message?" · "+x.message:"")).join("\n");
 $("batchStop").hidden=!running;
 $("batchPreview").disabled=running;
 $("batchStart").disabled=running||$("batchPreviewResult").hidden||!$("batchBackup").checked;
 $("batchBackup").disabled=running;
 $("batchQuality").disabled=running;
 $("batchGrayscale").disabled=running;
 $("batchReport").hidden=running;
 if(!running)say(j.state==="done"?"Coda completata. Puoi scaricare il report.":"Coda fermata. I file già convertiti sono salvati.");
}
async function poll(){
 try{render(await request("/batch/status"))}
 catch(error){say("Non riesco ad aggiornare la coda: "+error.message,true)}
}
try{
 const config=await request("/batch/config");
 if(config.enabled){
  panel.hidden=false;
  $("batchPreview").onclick=preview;
  $("batchBackup").onchange=()=>{
   $("batchStart").disabled=running||$("batchPreviewResult").hidden||!$("batchBackup").checked;
  };
  $("batchStart").onclick=async()=>{
   try{
    $("batchStart").disabled=true;
    render(await request("/batch/start",{
     path:selected,quality:$("batchQuality").value,
     grayscale:$("batchGrayscale").checked,
     backup_confirmed:$("batchBackup").checked
    }));
    $("batchReport").hidden=true;
   }catch(error){say(error.message,true);$("batchStart").disabled=false}
  };
  $("batchStop").onclick=async()=>{
   try{render(await request("/batch/stop",{}))}
   catch(error){say(error.message,true)}
  };
  await browse("");
  await poll();
  setInterval(poll,1800);
 }
}catch(_){
 // A private Codespace intentionally has no recursive overwrite interface.
}
