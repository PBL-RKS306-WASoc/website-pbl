from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import Length, Optional


class CancelOrderForm(FlaskForm):
    reason = StringField(validators=[Optional(), Length(max=200)])  # hanya dicatat di log