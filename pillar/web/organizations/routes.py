import logging

from flask import Blueprint, render_template, request, url_for
import flask_wtf.csrf
from flask_login import current_user

import pillar.flask_extra
from pillar import current_app
import pillar.api.users.avatar
from pillar.api.utils import authorization, str2id, jsonify
from pillar.web.system_util import pillar_api

from pillarsdk import Organization, User

log = logging.getLogger(__name__)
blueprint = Blueprint('pillar.web.organizations', __name__, url_prefix='/organizations')


@blueprint.route('/', endpoint='index')
def index(organization_id: str = None):
    api = pillar_api()

    organizations = Organization.all(api=api)

    if not organization_id and organizations['_items']:
        organization_id = organizations['_items'][0]._id

    can_create_organization = current_user.has_cap('create-organization')

    return render_template('organizations/index.html',
                           can_create_organization=can_create_organization,
                           organizations=organizations,
                           open_organization_id=organization_id)


@blueprint.route('/<organization_id>')
@pillar.flask_extra.vary_xhr()
def view_embed(organization_id: str):
    if not request.is_xhr:
        return index(organization_id)

    api = pillar_api()

    organization: Organization = Organization.find(organization_id, api=api)

    om = current_app.org_manager
    organization_oid = str2id(organization_id)

    members = om.org_members(organization.members)
    for member in members:
        member['avatar'] = pillar.api.users.avatar.url(member)
        member['_id'] = str(member['_id'])

    admin_user = User.find(organization.admin_uid, api=api)

    # Make sure it's never None
    organization.unknown_members = organization.unknown_members or []
    organization.human_ip_ranges = [ipr['human'] for ipr in (organization.ip_ranges or [])]

    can_super_edit = current_user.has_cap('admin')
    can_edit = can_super_edit or om.user_is_admin(organization_oid)

    csrf = flask_wtf.csrf.generate_csrf()

    return render_template('organizations/view_embed.html',
                           organization=organization,
                           admin_user=admin_user,
                           members=members,
                           can_edit=can_edit,
                           can_super_edit=can_super_edit,
                           seats_used=len(members) + len(organization.unknown_members),
                           csrf=csrf)


@blueprint.route('/create-new', methods=['POST'])
@authorization.require_login(require_cap='create-organization')
def create_new():
    """Creates a new Organization, owned by the currently logged-in user."""

    user_id = current_user.user_id
    log.info('Creating new organization for user %s', user_id)

    name = request.form['name']
    seat_count = int(request.form['seat_count'], 10)

    org_doc = current_app.org_manager.create_new_org(name, user_id, seat_count)

    org_id = str(org_doc['_id'])
    url = url_for('.view_embed', organization_id=org_id)
    resp = jsonify({'_id': org_id, 'location': url})
    resp.headers['Location'] = url

    return resp, 201
