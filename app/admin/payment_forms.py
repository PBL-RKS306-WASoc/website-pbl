from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import Length, Optional


class PaymentReviewForm(FlaskForm):
    reason = StringField(validators=[Optional(), Length(max=200)])  # alasan penolakan (hanya dicatat di log)