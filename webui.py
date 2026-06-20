import os
import sys
import glob
import json
import uuid
import subprocess
import threading
import time
import signal
import atexit
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template

sys.path.insert(0, str(Path(__file__).parent / "scripts"))

import storage
from storage import DOWNLOADS_DIR, WORK_DIR, DB_PATH, init_db, add_queue, get_stats, get_pending_queues

DENO_DIR = os.path.expanduser("~/.deno/bin")
if os.path.isdir(DENO_DIR) and DENO_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"{DENO_DIR}:{os.environ.get('PATH', '')}"

app = Flask(__name__)

init_db()

DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs = {}
daemon_process = None
daemon_lock = threading.Lock()
submissions = {}
submissions_lock = threading.Lock()
submission_id_counter = 0


def run_download(job_id, url, format_choice, format_id):
    job = jobs[job_id]
    out_template = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")

    cmd = ["yt-dlp", "--no-playlist", "-o", out_template]

    if format_choice == "audio":
        cmd += ["-x", "--audio-format", "mp3"]
    elif format_id:
        cmd += ["-f", f"{format_id}+bestaudio/best", "--merge-output-format", "mp4"]
    else:
        cmd += ["-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4"]

    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            job["status"] = "error"
            job["error"] = result.stderr.strip().split("\n")[-1]
            return

        files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{job_id}.*"))
        if not files:
            job["status"] = "error"
            job["error"] = "Download completed but no file was found"
            return

        if format_choice == "audio":
            target = [f for f in files if f.endswith(".mp3")]
            chosen = target[0] if target else files[0]
        else:
            target = [f for f in files if f.endswith(".mp4")]
            chosen = target[0] if target else files[0]

        for f in files:
            if f != chosen:
                try:
                    os.remove(f)
                except OSError:
                    pass

        job["status"] = "done"
        job["file"] = chosen
        ext = os.path.splitext(chosen)[1]
        title = job.get("title", "").strip()
        if title:
            safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()
            job["filename"] = f"{safe_title}{ext}" if safe_title else os.path.basename(chosen)
        else:
            job["filename"] = os.path.basename(chosen)
    except subprocess.TimeoutExpired:
        job["status"] = "error"
        job["error"] = "Download timed out (5 min limit)"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


def get_daemon_status():
    stats = get_stats()
    queues = get_pending_queues()

    pid_file = Path(WORK_DIR) / "daemon.pid"
    running = False
    pid = None
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            running = True
        except (ValueError, OSError):
            running = False

    return {
        "running": running,
        "pid": pid,
        "stats": stats,
        "queues": queues
    }


def start_daemon_background():
    global daemon_process
    with daemon_lock:
        pid_file = Path(WORK_DIR) / "daemon.pid"
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, 0)
                return {"success": False, "error": "Daemon already running"}
            except (ValueError, OSError):
                pass

        python = sys.executable
        script = str(Path(__file__).parent / "scripts" / "daemon_downloader.py")
        log_file = Path(WORK_DIR) / "daemon.log"

        with open(log_file, "a") as log:
            proc = subprocess.Popen(
                [python, script],
                stdout=log,
                stderr=log,
                start_new_session=True
            )

        pid_file.write_text(str(proc.pid))
        return {"success": True, "pid": proc.pid}


def stop_daemon_background():
    pid_file = Path(WORK_DIR) / "daemon.pid"
    if not pid_file.exists():
        return {"success": False, "error": "Daemon not running"}

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 15)
        for _ in range(10):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except OSError:
                break
        else:
            os.kill(pid, 9)
    except (ValueError, OSError):
        pass

    pid_file.unlink(missing_ok=True)
    return {"success": True}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    cmd = ["yt-dlp", "--no-playlist", "-j", url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip().split("\n")[-1]}), 400

        info = json.loads(result.stdout)

        best_by_height = {}
        for f in info.get("formats", []):
            height = f.get("height")
            if height and f.get("vcodec", "none") != "none":
                tbr = f.get("tbr") or 0
                if height not in best_by_height or tbr > (best_by_height[height].get("tbr") or 0):
                    best_by_height[height] = f

        formats = []
        for height, f in best_by_height.items():
            formats.append({
                "id": f["format_id"],
                "label": f"{height}p",
                "height": height,
            })
        formats.sort(key=lambda x: x["height"], reverse=True)

        return jsonify({
            "title": info.get("title", ""),
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration"),
            "uploader": info.get("uploader", ""),
            "formats": formats,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out fetching video info"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.json
    url = data.get("url", "").strip()
    format_choice = data.get("format", "video")
    format_id = data.get("format_id")
    title = data.get("title", "")

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    job_id = uuid.uuid4().hex[:10]
    jobs[job_id] = {"status": "downloading", "url": url, "title": title}

    thread = threading.Thread(target=run_download, args=(job_id, url, format_choice, format_id))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def check_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "error": job.get("error"),
        "filename": job.get("filename"),
    })


@app.route("/api/file/<job_id>")
def download_file(job_id):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "File not ready"}), 404
    return send_file(job["file"], as_attachment=True, download_name=job["filename"])


@app.route("/api/daemon/status")
def api_daemon_status():
    return jsonify(get_daemon_status())


@app.route("/api/daemon/start", methods=["POST"])
def api_daemon_start():
    return jsonify(start_daemon_background())


@app.route("/api/daemon/stop", methods=["POST"])
def api_daemon_stop():
    return jsonify(stop_daemon_background())


@app.route("/api/daemon/restart", methods=["POST"])
def api_daemon_restart():
    stop_daemon_background()
    time.sleep(1)
    return jsonify(start_daemon_background())


@app.route("/api/queue/reset", methods=["POST"])
def api_queue_reset():
    from storage import reset_stuck_downloads
    n = reset_stuck_downloads()
    return jsonify({"success": True, "reset": n})


def process_url_submission(sub_id, url):
    global submissions
    python = sys.executable
    script = str(Path(__file__).parent / "scripts" / "module1_fetch.py")

    with submissions_lock:
        submissions[sub_id]["status"] = "processing"

    result = subprocess.run(
        [python, script, url],
        capture_output=True,
        text=True,
        timeout=180
    )

    with submissions_lock:
        if result.returncode == 0:
            submissions[sub_id]["status"] = "done"
            submissions[sub_id]["output"] = result.stdout
        else:
            submissions[sub_id]["status"] = "error"
            submissions[sub_id]["error"] = result.stderr or result.stdout


@app.route("/api/queue/add", methods=["POST"])
def api_queue_add():
    global submission_id_counter
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    with submissions_lock:
        submission_id_counter += 1
        sub_id = f"sub_{submission_id_counter}"
        submissions[sub_id] = {"status": "pending", "url": url}

    thread = threading.Thread(target=process_url_submission, args=(sub_id, url))
    thread.daemon = True
    thread.start()

    return jsonify({"success": True, "submission_id": sub_id})


@app.route("/api/queue/submissions")
def api_queue_submissions():
    with submissions_lock:
        recent = dict(list(submissions.items())[-20:])
    return jsonify({"submissions": recent})


@app.route("/api/queue/list")
def api_queue_list():
    queues = get_pending_queues()
    return jsonify({"queues": queues})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8899))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, threaded=True)
