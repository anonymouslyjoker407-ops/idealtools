import os
import re
import uuid
import threading
import subprocess
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template_string, abort

# Render Free testing configuration.
# IMPORTANT: Free instances have limited RAM, CPU and temporary storage.
MAX_UPLOAD_BYTES = 1024 * 1024 * 1024  # 1 GB upload cap in this app
WORK_DIR = Path(os.environ.get("OCR_WORK_DIR", "/tmp/searchable_pdf"))
WORK_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

# Avoid OpenMP creating extra threads on low-memory instances.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

jobs = {}
jobs_lock = threading.Lock()
active_job_lock = threading.Lock()
active_job_id = None

PAGE = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Searchable PDF</title>
<style>
*{box-sizing:border-box}body{margin:0;padding:22px;background:#101522;color:#edf2ff;font-family:Arial,sans-serif}
main{max-width:650px;margin:40px auto;background:#1b2435;border:1px solid #34415a;border-radius:15px;padding:25px}
h1{font-size:25px;margin:0 0 10px}p{color:#bac6da;line-height:1.5}
label{display:block;margin:18px 0 8px;font-weight:bold}
input,select{width:100%;padding:12px;border:1px solid #4b5871;border-radius:8px;background:#101827;color:white}
button,.download{display:inline-block;margin-top:18px;padding:13px 18px;border:0;border-radius:8px;background:#7e9aff;color:#101522;font-weight:bold;text-decoration:none;cursor:pointer}
#status{margin-top:20px;white-space:pre-wrap;overflow-wrap:anywhere;background:#101827;border-radius:8px;padding:13px}
.warning{border:1px solid #8c7036;background:#332b1b;padding:12px;border-radius:8px;color:#ffe3a1}
small{color:#aebbd1}
</style>
</head>
<body><main>
<h1>Searchable PDF Converter</h1>
<p>PDF upload karo, language select karo aur searchable PDF download karo.</p>
<div class="warning"><b>Important:</b> App upload limit 1 GB rakhti hai, lekin Render Free par 1 GB PDF ya lakhon pages process hone ki guarantee nahi hai. Free instance ki RAM/CPU aur temporary storage bahut limited hain; service restart hone par processing/file delete ho sakti hai.</div>
<form id="form">
<label>PDF file</label><input type="file" name="pdf" accept=".pdf,application/pdf" required>
<label>OCR language</label>
<select name="language">
<option value="mar" selected>Marathi</option>
<option value="mar+eng">Marathi + English</option>
<option value="hin">Hindi</option>
<option value="hin+eng">Hindi + English</option>
<option value="eng">English</option>
<option value="mar+hin+eng">Marathi + Hindi + English</option>
</select>
<button id="submit">Make Searchable PDF</button>
</form>
<div id="status" hidden></div>
<a id="download" class="download" hidden>Download searchable.pdf</a>
</main>
<script>
const form=document.getElementById('form'), statusBox=document.getElementById('status');
const download=document.getElementById('download'), submit=document.getElementById('submit');
form.addEventListener('submit',async e=>{
 e.preventDefault(); submit.disabled=true; statusBox.hidden=false;
 statusBox.textContent='Uploading PDF... Please keep this page open.';
 download.hidden=true;
 try{
  const res=await fetch('/convert',{method:'POST',body:new FormData(form)});
  const data=await res.json();
  if(!res.ok) throw new Error(data.error||'Upload failed');
  const id=data.job_id;
  const timer=setInterval(async()=>{
   try{
    const s=await fetch('/status/'+id), j=await s.json();
    if(!s.ok) throw new Error(j.error||'Status unavailable');
    statusBox.textContent=j.message+(j.log?'\\n\\n'+j.log:'');
    if(j.status==='completed'){
     clearInterval(timer); download.href='/download/'+id; download.hidden=false; submit.disabled=false;
    } else if(j.status==='failed'){
     clearInterval(timer); submit.disabled=false;
    }
   }catch(err){clearInterval(timer);statusBox.textContent=err.message;submit.disabled=false;}
  },3000);
 }catch(err){statusBox.textContent=err.message;submit.disabled=false;}
});
</script></body></html>
"""

def valid_language(value):
    value = (value or "mar").strip().lower()
    if not re.fullmatch(r"[a-z]{3}(?:\+[a-z]{3})*", value):
        raise ValueError("Invalid language. Example: mar or mar+eng")
    return value

def run_ocr(job_id, input_path, output_path, language):
    command = [
        "ocrmypdf",
        "--language", language,
        "--jobs", "1",
        "--skip-text",
        "--optimize", "0",
        "--output-type", "pdf",
        str(input_path),
        str(output_path),
    ]
    try:
        env = os.environ.copy()
        env["OMP_THREAD_LIMIT"] = "1"
        env["OMP_NUM_THREADS"] = "1"
        with subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=env, bufsize=1
        ) as proc:
            tail = ""
            for line in proc.stdout:
                tail = (tail + line)[-10000:]
                with jobs_lock:
                    if job_id in jobs:
                        jobs[job_id]["log"] = tail
            code = proc.wait()
        if code == 0 and output_path.exists() and output_path.stat().st_size:
            with jobs_lock:
                jobs[job_id].update(status="completed", message="Searchable PDF ready hai.", log=tail)
        else:
            with jobs_lock:
                jobs[job_id].update(status="failed", message="OCR process fail hua. Logs check karo.", log=tail)
    except Exception as exc:
        with jobs_lock:
            jobs[job_id].update(status="failed", message=str(exc))
    finally:
        global active_job_id
        with active_job_lock:
            active_job_id = None

@app.errorhandler(413)
def too_large(_):
    return jsonify(error="Upload 1 GB app limit se bada hai, ya hosting platform ne request reject kar di."), 413

@app.get("/")
def index():
    return render_template_string(PAGE)

@app.get("/health")
def health():
    return jsonify(ok=True)

@app.post("/convert")
def convert():
    global active_job_id
    uploaded = request.files.get("pdf")
    if not uploaded or not uploaded.filename:
        return jsonify(error="PDF file select karo."), 400
    if not uploaded.filename.lower().endswith(".pdf"):
        return jsonify(error="Sirf PDF file allowed hai."), 400
    try:
        language = valid_language(request.form.get("language", "mar"))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    with active_job_lock:
        if active_job_id:
            return jsonify(error="Ek conversion already chal raha hai. Uske complete hone ka wait karo."), 409
        job_id = uuid.uuid4().hex
        job_dir = WORK_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(uploaded.filename).name
        input_path = job_dir / safe_name
        output_path = job_dir / "searchable.pdf"
        uploaded.save(input_path)
        if input_path.stat().st_size == 0:
            return jsonify(error="Uploaded PDF empty hai."), 400
        with jobs_lock:
            jobs[job_id] = {
                "status": "running",
                "message": "OCR processing shuru ho gayi hai.",
                "input": str(input_path),
                "output": str(output_path),
                "log": ""
            }
        active_job_id = job_id
    threading.Thread(target=run_ocr, args=(job_id, input_path, output_path, language), daemon=True).start()
    return jsonify(job_id=job_id), 202

@app.get("/status/<job_id>")
def status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify(error="Job nahi mila. Render restart par temporary files/jobs delete ho sakte hain."), 404
        return jsonify(status=job["status"], message=job["message"], log=job.get("log", "")[-10000:])

@app.get("/download/<job_id>")
def download(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job or job["status"] != "completed":
            abort(404)
        output_path = Path(job["output"])
    if not output_path.exists():
        abort(404)
    return send_file(output_path, as_attachment=True, download_name="searchable.pdf")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
