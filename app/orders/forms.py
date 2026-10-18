from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired
from wtforms import IntegerField, TextAreaField
from wtforms.validators import DataRequired, Length


class CheckoutForm(FlaskForm):
    shipping_address = TextAreaField(validators=[DataRequired(), Length(min=10, max=500)])
    # Total versi klien. Wajib ada & hanya dipakai untuk deteksi manipulasi, tidak untuk hitung.
    total_idr = IntegerField(validators=[DataRequired()])


class PaymentProofForm(FlaskForm):
    proof = FileField(validators=[FileRequired()])