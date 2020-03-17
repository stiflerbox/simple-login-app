import re
from email.utils import parseaddr

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators, ValidationError

from app.config import EMAIL_DOMAIN
from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.log import LOG
from app.models import GenEmail, Contact
from app.utils import random_string


def email_validator():
    """validate email address. Handle both only email and email with name:
    - ab@cd.com
    - AB CD <ab@cd.com>

    """
    message = "Invalid email format. Email must be either email@example.com or *First Last <email@example.com>*"

    def _check(form, field):
        email = field.data
        email = email.strip()
        email_part = email

        if "<" in email and ">" in email:
            if email.find("<") + 1 < email.find(">"):
                email_part = email[email.find("<") + 1 : email.find(">")].strip()

        if re.match(r"^[A-Za-z0-9\.\+_-]+@[A-Za-z0-9\._-]+\.[a-zA-Z]*$", email_part):
            return

        raise ValidationError(message)

    return _check


class NewContactForm(FlaskForm):
    email = StringField(
        "Email", validators=[validators.DataRequired(), email_validator()]
    )


@dashboard_bp.route("/alias_contact_manager/<alias_id>/", methods=["GET", "POST"])
@dashboard_bp.route(
    "/alias_contact_manager/<alias_id>/<contact_id>", methods=["GET", "POST"]
)
@login_required
def alias_contact_manager(alias_id, contact_id=None):
    gen_email = GenEmail.get(alias_id)

    # sanity check
    if not gen_email:
        flash("You do not have access to this page", "warning")
        return redirect(url_for("dashboard.index"))

    if gen_email.user_id != current_user.id:
        flash("You do not have access to this page", "warning")
        return redirect(url_for("dashboard.index"))

    new_contact_form = NewContactForm()

    if request.method == "POST":
        if request.form.get("form-name") == "create":
            if new_contact_form.validate():
                contact_email = new_contact_form.email.data.strip()

                # generate a reply_email, make sure it is unique
                # not use while to avoid infinite loop
                reply_email = f"ra+{random_string(25)}@{EMAIL_DOMAIN}"
                for _ in range(1000):
                    reply_email = f"ra+{random_string(25)}@{EMAIL_DOMAIN}"
                    if not Contact.get_by(reply_email=reply_email):
                        break

                _, website_email = parseaddr(contact_email)

                # already been added
                if Contact.get_by(
                    gen_email_id=gen_email.id, website_email=website_email
                ):
                    flash(f"{website_email} is already added", "error")
                    return redirect(
                        url_for("dashboard.alias_contact_manager", alias_id=alias_id)
                    )

                contact = Contact.create(
                    gen_email_id=gen_email.id,
                    website_email=website_email,
                    website_from=contact_email,
                    reply_email=reply_email,
                )

                LOG.d("create reverse-alias for %s", contact_email)
                db.session.commit()
                flash(f"Reverse alias for {contact_email} is created", "success")

                return redirect(
                    url_for(
                        "dashboard.alias_contact_manager",
                        alias_id=alias_id,
                        contact_id=contact.id,
                    )
                )
        elif request.form.get("form-name") == "delete":
            contact_id = request.form.get("contact-id")
            contact = Contact.get(contact_id)

            if not contact:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(
                    url_for("dashboard.alias_contact_manager", alias_id=alias_id)
                )
            elif contact.gen_email_id != gen_email.id:
                flash("You cannot delete reverse-alias", "warning")
                return redirect(
                    url_for("dashboard.alias_contact_manager", alias_id=alias_id)
                )

            contact_name = contact.website_from
            Contact.delete(contact_id)
            db.session.commit()

            flash(f"Reverse-alias for {contact_name} has been deleted", "success")

            return redirect(
                url_for("dashboard.alias_contact_manager", alias_id=alias_id)
            )

    # make sure highlighted contact is at array start
    contacts = gen_email.contacts

    if contact_id:
        contacts = sorted(contacts, key=lambda fe: fe.id == contact_id, reverse=True)

    return render_template(
        "dashboard/alias_contact_manager.html",
        contacts=contacts,
        alias=gen_email.email,
        gen_email=gen_email,
        new_contact_form=new_contact_form,
        contact_id=contact_id,
    )
