"""Organization management.

Assumes role names that are given to users by organization membership
start with the string "org-".
"""

import enum
import logging
import typing

import attr
import bson

from pillar import attrs_extra, current_app
from pillar.api.utils import remove_private_keys


class OrganizationError(Exception):
    """Superclass for all Organization-related errors."""


@attr.s
class NotEnoughSeats(OrganizationError):
    """Thrown when trying to add too many members to the organization."""

    org_id = attr.ib(validator=attr.validators.instance_of(bson.ObjectId))
    seat_count = attr.ib(validator=attr.validators.instance_of(int))
    attempted_seat_count = attr.ib(validator=attr.validators.instance_of(int))


@attr.s
class OrgManager:
    """Organization manager.

    Performs actions on an Organization. Does *NOT* test user permissions -- the caller
    is responsible for that.
    """

    _log = attrs_extra.log('%s.OrgManager' % __name__)

    def create_new_org(self,
                       name: str,
                       admin_uid: bson.ObjectId,
                       seat_count: int,
                       *,
                       org_roles: typing.Iterable[str] = None) -> dict:
        """Creates a new Organization.

        Returns the new organization document.
        """

        assert isinstance(admin_uid, bson.ObjectId)

        org_doc = {
            'name': name,
            'admin_uid': admin_uid,
            'seat_count': seat_count,
        }

        if org_roles:
            org_doc['org_roles'] = list(org_roles)

        r, _, _, status = current_app.post_internal('organizations', org_doc)
        if status != 201:
            self._log.error('Error creating organization; status should be 201, not %i: %s',
                            status, r)
            raise ValueError(f'Unable to create organization, status code {status}')

        org_doc.update(r)
        return org_doc

    def assign_users(self,
                     org_id: bson.ObjectId,
                     emails: typing.List[str]) -> dict:
        """Assigns users to the organization.

        Checks the seat count and throws a NotEnoughSeats exception when the
        seat count is not sufficient to assign the requested users.

        Users are looked up by email address, and known users are
        automatically mapped.

        :returns: the new organization document.
        """

        self._log.info('Adding %i new members to organization %s', len(emails), org_id)

        users_coll = current_app.db('users')
        existing_user_docs = list(users_coll.find({'email': {'$in': emails}},
                                                  projection={'_id': 1, 'email': 1}))
        unknown_users = set(emails) - {user['email'] for user in existing_user_docs}
        existing_users = {user['_id'] for user in existing_user_docs}

        if self._log.isEnabledFor(logging.INFO):
            self._log.info('  - found users: %s', ', '.join(str(uid) for uid in existing_users))
            self._log.info('  - unknown users: %s', ', '.join(unknown_users))

        org_doc = self._get_org(org_id)

        # Compute the new members.
        members = set(org_doc.get('members') or []) | existing_users
        unknown_members = set(org_doc.get('unknown_members')) | unknown_users

        # Make sure we don't exceed the current seat count.
        new_seat_count = len(members) + len(unknown_members)
        if new_seat_count > org_doc['seat_count']:
            self._log.warning('assign_users(%s, ...): Trying to increase seats to %i, '
                              'but org only has %i seats.',
                              org_id, new_seat_count, org_doc['seat_count'])
            raise NotEnoughSeats(org_id, org_doc['seat_count'], new_seat_count)

        # Update the organization.
        org_doc['members'] = list(members)
        org_doc['unknown_members'] = list(unknown_members)

        r, _, _, status = current_app.put_internal('organizations',
                                                   remove_private_keys(org_doc),
                                                   _id=org_id)
        if status != 200:
            self._log.error('Error updating organization; status should be 200, not %i: %s',
                            status, r)
            raise ValueError(f'Unable to update organization, status code {status}')
        org_doc.update(r)

        # Update the roles for the affected members
        for uid in existing_users:
            self.refresh_roles(uid)

        return org_doc

    def remove_user(self,
                    org_id: bson.ObjectId,
                    *,
                    user_id: bson.ObjectId = None,
                    email: str = None) -> dict:
        """Removes a user from the organization.

        The user can be identified by either user ID or email.

        Returns the new organization document.
        """

        users_coll = current_app.db('users')

        assert user_id or email

        # Collect the email address if not given. This ensures the removal
        # if the email was accidentally in the unknown_members list.
        if email is None:
            user_doc = users_coll.find_one(user_id, projection={'email': 1})
            if user_doc is not None:
                email = user_doc['email']

        # See if we know this user.
        if user_id is None:
            user_doc = users_coll.find_one({'email': email}, projection={'_id': 1})
            if user_doc is not None:
                user_id = user_doc['_id']

        self._log.info('Removing user %s / %s from organization %s', user_id, email, org_id)

        org_doc = self._get_org(org_id)

        # Compute the new members.
        if user_id:
            members = set(org_doc.get('members') or []) - {user_id}
            org_doc['members'] = list(members)

        if email:
            unknown_members = set(org_doc.get('unknown_members')) - {email}
            org_doc['unknown_members'] = list(unknown_members)

        r, _, _, status = current_app.put_internal('organizations',
                                                   remove_private_keys(org_doc),
                                                   _id=org_id)
        if status != 200:
            self._log.error('Error updating organization; status should be 200, not %i: %s',
                            status, r)
            raise ValueError(f'Unable to update organization, status code {status}')
        org_doc.update(r)

        # Update the roles for the affected member.
        if user_id:
            self.refresh_roles(user_id)

        return org_doc

    def _get_org(self, org_id: bson.ObjectId):
        """Returns the organization, or raises a ValueError."""

        assert isinstance(org_id, bson.ObjectId)

        org_coll = current_app.db('organizations')
        org = org_coll.find_one(org_id)
        if org is None:
            raise ValueError(f'Organization {org_id} not found')
        return org

    def refresh_roles(self, user_id: bson.ObjectId):
        """Refreshes the user's roles to own roles + organizations' roles."""

        from pillar.api.service import do_badger

        org_coll = current_app.db('organizations')

        # Aggregate all org-given roles for this user.
        query = org_coll.aggregate([
            {'$match': {'members': user_id}},
            {'$project': {'org_roles': 1}},
            {'$unwind': {'path': '$org_roles'}},
            {'$group': {
                '_id': None,
                'org_roles': {'$addToSet': '$org_roles'},
            }}])

        # If the user has no organizations at all, the query will have no results.
        try:
            org_roles_doc = query.next()
        except StopIteration:
            org_roles = set()
        else:
            org_roles = set(org_roles_doc['org_roles'])

        users_coll = current_app.db('users')
        user_doc = users_coll.find_one(user_id, projection={'roles': 1})

        all_user_roles = set(user_doc.get('roles') or [])
        existing_org_roles = {role for role in all_user_roles
                              if role.startswith('org-')}

        grant_roles = org_roles - all_user_roles
        revoke_roles = existing_org_roles - org_roles

        if grant_roles:
            do_badger('grant', roles=grant_roles, user_id=user_id)
        if revoke_roles:
            do_badger('revoke', roles=revoke_roles, user_id=user_id)

# def setup_app(app):
#     from . import eve_hooks, api, patch
#
#     eve_hooks.setup_app(app)
#     api.setup_app(app)
#     patch.setup_app(app)
