from flask_wtf import FlaskForm
from wtforms import IntegerField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange


class ReviewForm(FlaskForm):
    rating = IntegerField(
        "Rating (1-5)",
        validators=[DataRequired(), NumberRange(min=1, max=5)],
    )
    comment = TextAreaField("Ulasan", validators=[Length(max=1000)])
    submit = SubmitField("Kirim Ulasan")
