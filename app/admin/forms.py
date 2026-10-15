from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange


class CategoryForm(FlaskForm):
    name = StringField("Nama Kategori", validators=[DataRequired(), Length(max=80)])
    submit = SubmitField("Tambah Kategori")


class ProductForm(FlaskForm):
    name = StringField("Nama Barang", validators=[DataRequired(), Length(max=150)])
    category_id = SelectField("Kategori", coerce=int, validators=[DataRequired()])
    price_idr = IntegerField(
        "Harga (Rp)",
        validators=[DataRequired(), NumberRange(min=0, message="Harga tidak boleh minus")],
    )
    stock = IntegerField(
        "Stok",
        validators=[DataRequired(), NumberRange(min=0, message="Stok tidak boleh minus")],
    )
    description = TextAreaField("Deskripsi Barang")
    is_active = BooleanField("Tampilkan di Katalog (Aktif)", default=True)
    submit = SubmitField("Simpan Barang")