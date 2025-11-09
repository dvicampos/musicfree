import os
import io
import glob
import shutil
import tempfile
from pathlib import Path
from datetime import datetime

from flask import (
    Flask, render_template, request, send_file,
    Response, stream_with_context, jsonify
)
import yt_dlp

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")

# ========= Helpers =========
def build_yt_options(tmp_dir, codec, quality, use_cookies=False, cookie_path=None):
    # Preferencias de formato base
    fmt = "bestaudio/best"
    if codec == "m4a":
        fmt = "bestaudio[ext=m4a]/bestaudio/best"
    elif codec == "opus":
        fmt = "251/bestaudio/best"  # webm/opus común

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
        "http_headers": {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36"),
            "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
        },
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        "postprocessors": postprocessors,
        "quiet": True,
        "no_warnings": True,
    }
    if use_cookies and cookie_path and Path(cookie_path).exists():
        opts["cookiefile"] = cookie_path
    return opts


def find_output_file(tmp_dir):
    # Busca el archivo resultante post-FFmpeg en el directorio temporal
    files = [p for p in Path(tmp_dir).glob("*") if p.is_file()]
    if not files:
        return None
    # Escoge el más reciente (por si se generó intermedio + final)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


# ========= Rutas =========
@app.get("/")
def index():
    return render_template("index.html")


@app.post("/download")
def download():
    """
    Recibe: url, codec (mp3/m4a/opus), quality (kbps), usar cookies opcional.
    Descarga en un directorio temporal, responde stream como attachment,
    y borra todo al finalizar la transmisión.
    """
    url = (request.form.get("url") or "").strip()
    codec = request.form.get("codec", "mp3").strip().lower()
    quality = request.form.get("quality", "192").strip()
    use_cookies = request.form.get("use_cookies") == "on"

    if not url:
        return jsonify({"ok": False, "error": "Falta la URL de YouTube."}), 400

    # Directorio temporal para esta descarga
    tmp_dir = tempfile.mkdtemp(prefix="yt_")

    # Manejo de cookies opcional
    cookie_path = None
    if use_cookies:
        f = request.files.get("cookies_file")
        if f and f.filename:
            cookie_path = os.path.join(tmp_dir, "cookies.txt")
            f.save(cookie_path)

    # Prepara yt-dlp
    ytdl_opts = build_yt_options(
        tmp_dir=tmp_dir, codec=codec, quality=quality,
        use_cookies=use_cookies, cookie_path=cookie_path
    )

    try:
        with yt_dlp.YoutubeDL(ytdl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "audio")
    except Exception as e:
        # Limpieza por error
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({"ok": False, "error": f"Ocurrió un error: {e}"}), 500

    # Localiza el archivo final
    out_file = find_output_file(tmp_dir)
    if not out_file or not out_file.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({"ok": False, "error": "No se generó el archivo de salida."}), 500

    # Nombre de descarga amigable
    dl_name = f"{title}.{out_file.suffix.lstrip('.')}"
    mime = "audio/mpeg"
    if out_file.suffix.lower() == ".m4a":
        mime = "audio/mp4"
    elif out_file.suffix.lower() == ".opus":
        mime = "audio/ogg"

    # Stream + limpieza (sin persistir en el servidor)
    def stream_and_cleanup(path, tmp_to_remove):
        try:
            with open(path, "rb") as f:
                chunk = f.read(8192)
                while chunk:
                    yield chunk
                    chunk = f.read(8192)
        finally:
            # Borra archivo y directorio temporal
            try:
                os.remove(path)
            except Exception:
                pass
            try:
                shutil.rmtree(tmp_to_remove, ignore_errors=True)
            except Exception:
                pass

    return Response(
        stream_with_context(stream_and_cleanup(str(out_file), tmp_dir)),
        headers={
            "Content-Disposition": f'attachment; filename="{dl_name}"',
            "Content-Type": mime,
            "Cache-Control": "no-store",
        }
    )


if __name__ == "__main__":
    # python app.py
    # http://127.0.0.1:5000/
    app.run(debug=True)
