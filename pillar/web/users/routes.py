import json
import logging
import requests

from flask import (abort, Blueprint, current_app, flash, redirect,
                   render_template, request, session, url_for)
from flask_login import login_required, login_user, logout_user, current_user
from flask_oauthlib.client import OAuthException
from pillar.auth import UserClass
from pillar.web import system_util
from .forms import UserProfileForm
from .forms import UserSettingsEmailsForm
from .forms import UserEditForm
from .forms import UserLoginForm
from pillarsdk import exceptions as sdk_exceptions
from pillarsdk.users import User
from pillarsdk.groups import Group

log = logging.getLogger(__name__)
blueprint = Blueprint('users', __name__)


def check_oauth_provider(provider):
    if not provider:
        return abort(404)


@blueprint.route('/login')
def login():
    check_oauth_provider(current_app.oauth_blender_id)

    session['next_after_login'] = request.args.get('next') or request.referrer

    callback = url_for(
        'users.blender_id_authorized',
        _external=True,
        _scheme=current_app.config['SCHEME']
    )
    return current_app.oauth_blender_id.authorize(callback=callback)


@blueprint.route('/oauth/blender-id/authorized')
def blender_id_authorized():
    check_oauth_provider(current_app.oauth_blender_id)
    oauth_resp = current_app.oauth_blender_id.authorized_response()
    if oauth_resp is None:
        return 'Access denied: reason=%s error=%s' % (
            request.args['error_reason'],
            request.args['error_description']
        )
    if isinstance(oauth_resp, OAuthException):
        return 'Access denied: %s' % oauth_resp.message

    session['blender_id_oauth_token'] = (oauth_resp['access_token'], '')

    user = UserClass(oauth_resp['access_token'])
    login_user(user)
    # user = load_user(current_user.id)

    if user is not None:
        pass
        # Check with the store for user roles. If the user has an active
        # subscription, we apply the 'subscriber' role
        # user_roles_update(user.objectid)

    next_after_login = session.get('next_after_login')
    if next_after_login:
        del session['next_after_login']
        return redirect(next_after_login)
    return redirect(url_for('main.homepage'))


@blueprint.route('/login/local', methods=['GET', 'POST'])
def login_local():
    """Login with a local account, skipping OAuth. This provides access only
    to the web application and is meant for limited access (for example in
    the case of a shared account)."""
    form = UserLoginForm()
    # Forward credentials to server
    if form.validate_on_submit():
        payload = {
            'username': form.username.data,
            'password': form.password.data
            }
        r = requests.post("{0}auth/make-token".format(
            system_util.pillar_server_endpoint()), data=payload)
        if r.status_code != 200:
            return abort(r.status_code)
        res = r.json()
        # If correct, receive token and log in the user
        user = UserClass(res['token'])
        login_user(user)
        return redirect(url_for('main.homepage'))
    return render_template('users/login.html', form=form)


@blueprint.route('/logout')
def logout():
    logout_user()
    session.clear()
    return redirect('/')


@blueprint.route('/settings/profile', methods=['GET', 'POST'])
@login_required
def settings_profile():
    """Profile view and edit page. This is a temporary implementation.
    """
    if current_user.has_role('protected'):
        return abort(404)  # TODO: make this 403, handle template properly
    api = system_util.pillar_api()
    user = User.find(current_user.objectid, api=api)

    form = UserProfileForm(
        full_name=user.full_name,
        username=user.username)

    if form.validate_on_submit():
        try:
            user.full_name = form.full_name.data
            user.username = form.username.data
            user.update(api=api)
            flash("Profile updated", 'success')
        except sdk_exceptions.ResourceInvalid as e:
            message = json.loads(e.content)
            flash(message)

    return render_template('users/settings/profile.html', form=form, title='profile')


@blueprint.route('/settings/emails', methods=['GET', 'POST'])
@login_required
def settings_emails():
    """Main email settings.
    """
    if current_user.has_role('protected'):
        return abort(404)  # TODO: make this 403, handle template properly
    api = system_util.pillar_api()
    user = User.find(current_user.objectid, api=api)

    # Force creation of settings for the user (safely remove this code once
    # implemented on account creation level, and after adding settings to all
    # existing users)
    if not user.settings:
        user.settings = dict(email_communications=1)
        user.update(api=api)

    if user.settings.email_communications is None:
        user.settings.email_communications = 1
        user.update(api=api)

    # Generate form
    form = UserSettingsEmailsForm(
        email_communications=user.settings.email_communications)

    if form.validate_on_submit():
        try:
            user.settings.email_communications = form.email_communications.data
            user.update(api=api)
            flash("Profile updated", 'success')
        except sdk_exceptions.ResourceInvalid as e:
            message = json.loads(e.content)
            flash(message)

    return render_template('users/settings/emails.html', form=form, title='emails')


@blueprint.route('/settings/billing')
@login_required
def settings_billing():
    """View the subscription status of a user
    """
    if current_user.has_role('protected'):
        return abort(404)  # TODO: make this 403, handle template properly
    api = system_util.pillar_api()
    user = User.find(current_user.objectid, api=api)
    groups = []
    if user.groups:
        for group_id in user.groups:
            group = Group.find(group_id, api=api)
            groups.append(group.name)
    external_subscriptions_server = current_app.config['EXTERNAL_SUBSCRIPTIONS_MANAGEMENT_SERVER']
    r = requests.get(external_subscriptions_server, params={'blenderid': user.email})
    store_user = r.json()
    return render_template(
        'users/settings/billing.html',
        store_user=store_user, groups=groups, title='billing')


@blueprint.route('/u/<user_id>/edit', methods=['GET', 'POST'])
@login_required
def users_edit(user_id):
    if not current_user.has_role('admin'):
        return abort(403)
    api = system_util.pillar_api()
    user = User.find(user_id, api=api)
    form = UserEditForm()
    if form.validate_on_submit():
        def get_groups(roles):
            """Return a set of role ids matching the group names provided"""
            groups_set = set()
            for system_role in roles:
                group = Group.find_one({'where': "name=='%s'" % system_role}, api=api)
                groups_set.add(group._id)
            return groups_set

        # Remove any of the default roles
        system_roles = set([role[0] for role in form.roles.choices])
        system_groups = get_groups(system_roles)
        # Current user roles
        user_roles_list = user.roles if user.roles else []
        user_roles = set(user_roles_list)
        user_groups = get_groups(user_roles_list)
        # Remove all form roles from current roles
        user_roles = list(user_roles.difference(system_roles))
        user_groups = list(user_groups.difference(system_groups))
        # Get the assigned roles
        system_roles_assigned = form.roles.data
        system_groups_assigned = get_groups(system_roles_assigned)
        # Reassign roles based on form.roles.data by adding them to existing roles
        user_roles += system_roles_assigned
        user_groups += list(get_groups(user_roles))
        # Fetch the group for the assigned system roles
        user.roles = user_roles
        user.groups = user_groups
        user.update(api=api)
    else:
        form.roles.data = user.roles
    return render_template('users/edit_embed.html',
        user=user,
        form=form)


@blueprint.route('/u')
@login_required
def users_index():
    if not current_user.has_role('admin'):
        return abort(403)
    return render_template('users/index.html')
