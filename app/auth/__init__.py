import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..logging_setup import log_event
from ..models import User
from .forms import LoginForm, ProfileForm, RegisterForm

bp = Blueprint("auth", __name__, url_prefix="/auth")


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
@login_required
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
            current_user.email = form.email.data
            current_user.full_name = form.full_name.data
            db.session.commit()
            log_event(
                "profile.updated",
                user_id=current_user.id,
                username=current_user.username,
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