from flask_wtf import FlaskForm
from wtforms import IntegerField
from wtforms.validators import DataRequired, InputRequired, NumberRange, Optional


class AddToCartForm(FlaskForm):
    product_id = IntegerField(validators=[DataRequired()])
    quantity = IntegerField(default=1, validators=[DataRequired(), NumberRange(min=1, max=99)])
    # Harga yang ditampilkan ke klien. HANYA untuk deteksi manipulasi, tidak pernah dipakai untuk hitung.
    price_idr = IntegerField(validators=[Optional()])


class UpdateCartForm(FlaskForm):
    quantity = IntegerField(validators=[InputRequired(), NumberRange(min=0, max=99)])  # 0 = hapus


class RemoveFromCartForm(FlaskForm):
    """Form kosong, hanya untuk validasi CSRF."""