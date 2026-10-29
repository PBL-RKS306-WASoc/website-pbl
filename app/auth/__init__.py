import logging
import os
import uuid
from functools import wraps
from io import BytesIO

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..logging_setup import log_event
from ..models import User
from .forms import LoginForm, ProfileForm, RegisterForm

bp = Blueprint("auth", __name__, url_prefix="/auth")
AVATAR_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG"}
MAX_AVATAR_DIMENSION = 4096


def _avatar_dir():
    folder = current_app.config["UPLOAD_FOLDER"]
    if not os.path.isabs(folder):
        folder = os.path.join(os.path.dirname(current_app.root_path), folder)
    return os.path.join(folder, "avatars")


def _process_avatar(upload):
    extension = os.path.splitext(upload.filename or "")[1].lower()
    expected_format = AVATAR_FORMATS.get(extension)
    if not expected_format:
        return None, "Format avatar harus JPG atau PNG."

    try:
        image = Image.open(upload.stream)
        if image.format != expected_format:
            return None, "Isi berkas tidak sesuai dengan ekstensi JPG atau PNG."
        image = ImageOps.exif_transpose(image)
        if image.width > MAX_AVATAR_DIMENSION or image.height > MAX_AVATAR_DIMENSION:
            return None, "Ukuran gambar maksimal 4096 x 4096 piksel."

        output = BytesIO()
        if expected_format == "JPEG":
            image.convert("RGB").save(output, format="JPEG", optimize=True)
            extension = ".jpg"
        else:
            image.convert("RGBA").save(output, format="PNG", optimize=True)
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        return None, "Berkas avatar bukan gambar yang valid."

    return (output.getvalue(), extension), None


def _remove_avatar(filename):
    if not filename:
        return
    try:
        os.remove(os.path.join(_avatar_dir(), os.path.basename(filename)))
    except FileNotFoundError:
        pass
    except OSError:
        current_app.logger.exception("Gagal menghapus berkas avatar lama.")


def _customer_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("auth.login"))

    form = RegisterForm()
    if form.validate_on_submit():
        # 1. Cek apakah username atau email sudah pernah dipakai
        existing_user = User.query.filter(
            (User.username == form.username.data) | (User.email == form.email.data)
        ).first()
        if existing_user:
            flash("Username atau email sudah terdaftar.", "danger")
            return render_template("auth/register.html", form=form)

        # 2. Simpan user baru ke database (password otomatis di-hash dengan Argon2)
        user = User(
            username=form.username.data,
            email=form.email.data,
            full_name=form.full_name.data,
            role="customer",
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        # 3. Catat ke log aplikasi
        log_event(
            "auth.register",
            user_id=user.id,
            username=user.username,
            src_ip=request.remote_addr,
            method=request.method,
            path=request.path,
        )
        flash("Registrasi berhasil! Silakan login.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect("/")

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()

        # Jika user ada DAN password cocok
        if user and user.check_password(form.password.data):
            # Akun dinonaktifkan/dikunci: tolak setelah password benar (tidak membocorkan status ke tebakan salah)
            if not user.is_active:
                log_event(
                    "auth.login_blocked",
                    level=logging.WARNING,
                    user_id=user.id,
                    username=user.username,
                    reason="disabled" if not user.is_enabled else "locked",
                    src_ip=request.remote_addr,
                    method=request.method,
                    path=request.path,
                )
                flash("Akun Anda dinonaktifkan atau dikunci sementara. Hubungi admin.", "danger")
                return render_template("auth/login.html", form=form)
            login_user(user)
            log_event(
                "auth.login_success",
                user_id=user.id,
                username=user.username,
                src_ip=request.remote_addr,
                method=request.method,
                path=request.path,
            )
            flash("Berhasil login!", "success")
            return redirect("/")

        # Jika gagal: pesan error umum (tidak membocorkan mana yang salah) & catat ke log
        log_event(
            "auth.login_failed",
            level=logging.WARNING,
            username=form.username.data,
            src_ip=request.remote_addr,
            method=request.method,
            path=request.path,
        )
        flash("Username atau password salah.", "danger")

    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    log_event(
        "auth.logout",
        user_id=current_user.id,
        username=current_user.username,
        src_ip=request.remote_addr,
        method=request.method,
        path=request.path,
    )
    logout_user()
    flash("Anda telah logout.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/profile", methods=["GET", "POST"])
@_customer_required
def profile():
    form = ProfileForm()
    if form.validate_on_submit():
        existing_user = User.query.filter(
            User.email == form.email.data,
            User.id != current_user.id,
        ).first()
        if existing_user:
            form.email.errors.append("Email sudah digunakan akun lain.")
        else:
            avatar_data = None
            avatar_filename = None
            if form.avatar.data and form.avatar.data.filename:
                avatar_data, error = _process_avatar(form.avatar.data)
                if error:
                    form.avatar.errors.append(error)
                else:
                    avatar_filename = f"{uuid.uuid4().hex}{avatar_data[1]}"

            if not form.avatar.errors:
                previous_avatar = current_user.avatar_filename
                if avatar_filename:
                    os.makedirs(_avatar_dir(), exist_ok=True)
                    with open(os.path.join(_avatar_dir(), avatar_filename), "wb") as file:
                        file.write(avatar_data[0])

                current_user.email = form.email.data
                current_user.full_name = form.full_name.data
                if avatar_filename:
                    current_user.avatar_filename = avatar_filename

                try:
                    db.session.commit()
                except SQLAlchemyError:
                    db.session.rollback()
                    _remove_avatar(avatar_filename)
                    raise

                if avatar_filename:
                    _remove_avatar(previous_avatar)
                log_event(
                    "profile.updated",
                    user_id=current_user.id,
                    username=current_user.username,
                    avatar_updated=bool(avatar_filename),
                    src_ip=request.remote_addr,
                    method=request.method,
                    path=request.path,
                )
                flash("Profil berhasil diperbarui.", "success")
                return redirect(url_for("auth.profile"))
    elif request.method == "GET":
        form.email.data = current_user.email
        form.full_name.data = current_user.full_name

    return render_template("auth/profile.html", form=form)


@bp.route("/avatar")
@_customer_required
def avatar():
    if not current_user.avatar_filename:
        abort(404)
    return send_from_directory(
        _avatar_dir(),
        os.path.basename(current_user.avatar_filename),
        mimetype="image/png" if current_user.avatar_filename.endswith(".png") else "image/jpeg",
    )