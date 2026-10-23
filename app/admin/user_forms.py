from flask_wtf import FlaskForm
from wtforms import IntegerField, SelectField, StringField
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional


class RoleForm(FlaskForm):
    role = SelectField(choices=[("customer", "customer"), ("admin", "admin")],
                       validators=[DataRequired()])


class LockForm(FlaskForm):
    minutes = IntegerField(validators=[InputRequired(), NumberRange(min=1, max=10080)])
    reason = StringField(validators=[Optional(), Length(max=200)])


class ReasonForm(FlaskForm):
    reason = StringField(validators=[Optional(), Length(max=200)])


class ActionForm(FlaskForm):
    """Form kosong, hanya untuk validasi CSRF."""