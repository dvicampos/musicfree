import os
import io
import shutil
import tempfile
from pathlib import Path
from flask import (
    Flask, render_template, request, Response,
    stream_with_context, jsonify
)
import yt_dlp

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")

# Puedes setear un proxy residencial en Render > Environment:
# YTDLP_PROXY = http://user:pass@host:puerto  (o socks5://…)
PROXY = os.getenv("YTDLP_PROXY")

def build_yt_options(tmp_dir, codec, quality, cookie_path=None):
    fmt = "bestaudio/best"
    if codec == "m4a":
        fmt = "bestaudio[ext=m4a]/bestaudio/best"
    elif codec == "opus":
        fmt = "251/bestaudio/best"

    postprocessors = [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": codec,
        "preferredquality": quality,
    }]

    opts = {
        "format": fmt,
        "noplaylist": True,
        "outtmpl": str(Path(tmp_dir) / "%(title)s.%(ext)s"),
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 1,

        # Headers tipo navegador
        "http_headers": {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36"),
            "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
        },

        # Alterna clients de YouTube (suele ayudar)
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},

        # Silencio en logs del server
        "quiet": True,
        "no_warnings": True,
    }

    if cookie_path and Path(cookie_path).exists():
        opts["cookiefile"] = cookie_path

    # Proxy si lo definiste
    if PROXY:
        opts["proxy"] = PROXY

    return opts

def find_output_file(tmp_dir):
    files = [p for p in Path(tmp_dir).glob("*") if p.is_file()]
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]

@app.get("/")
def index():
    # Detecta si estás en Render (ayuda a mostrar aviso UI)
    on_render = bool(os.getenv("RENDER"))
    return render_template("index.html", on_render=on_render, proxy=bool(PROXY))

@app.post("/download")
def download():
    url = (request.form.get("url") or "").strip()
    codec = request.form.get("codec", "mp3").strip().lower()
    quality = request.form.get("quality", "192").strip()

    # Cookies vía archivo o textarea (pegadas)
    cookies_text = (request.form.get("cookies_text") or "").strip()
    use_cookies = request.form.get("use_cookies") == "on"
    file_cookies = request.files.get("cookies_file")

    if not url:
        return jsonify({"ok": False, "error": "Falta la URL de YouTube."}), 400

    tmp_dir = tempfile.mkdtemp(prefix="yt_")
    cookie_path = None

    try:
        if use_cookies:
            if file_cookies and file_cookies.filename:
                cookie_path = os.path.join(tmp_dir, "cookies.txt")
                file_cookies.save(cookie_path)
            elif cookies_text:
                cookie_path = os.path.join(tmp_dir, "cookies.txt")
                with open(cookie_path, "w", encoding="utf-8") as f:
                    f.write(cookies_text)

        ytdl_opts = build_yt_options(
            tmp_dir=tmp_dir, codec=codec, quality=quality, cookie_path=cookie_path
        )

        with yt_dlp.YoutubeDL(ytdl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "audio")

        out_file = find_output_file(tmp_dir)
        if not out_file or not out_file.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return jsonify({"ok": False, "error": "No se generó el archivo de salida."}), 500

        dl_name = f"{title}.{out_file.suffix.lstrip('.')}"
        mime = "audio/mpeg"
        if out_file.suffix.lower() == ".m4a":
            mime = "audio/mp4"
        elif out_file.suffix.lower() == ".opus":
            mime = "audio/ogg"

        def stream_and_cleanup(path, tmp_to_remove):
            try:
                with open(path, "rb") as f:
                    chunk = f.read(8192)
                    while chunk:
                        yield chunk
                        chunk = f.read(8192)
            finally:
                try: os.remove(path)
                except Exception: pass
                try: shutil.rmtree(tmp_to_remove, ignore_errors=True)
                except Exception: pass

        return Response(
            stream_with_context(stream_and_cleanup(str(out_file), tmp_dir)),
            headers={
                "Content-Disposition": f'attachment; filename="{dl_name}"',
                "Content-Type": mime,
                "Cache-Control": "no-store",
            }
        )

    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        # Mensaje más claro si es el caso típico de cookies
        msg = str(e)
        if "Sign in to confirm you're not a bot" in msg or "confirm you’re not a bot" in msg:
            msg += " · Sube o pega tus cookies de YouTube (estando logueado) o configura un proxy residencial."
        return jsonify({"ok": False, "error": f"Ocurrió un error: {msg}"}), 500
