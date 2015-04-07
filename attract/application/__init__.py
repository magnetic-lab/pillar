import os

from eve import Eve

# import random
# import string

from eve.auth import TokenAuth
from eve.auth import BasicAuth
from eve.io.mongo import Validator
from bson import ObjectId


class SystemUtility():
    def __new__(cls, *args, **kwargs):
        raise TypeError("Base class may not be instantiated")

    @staticmethod
    def blender_id_endpoint():
        """Gets the endpoint for the authentication API. If the env variable
        is defined, it's possible to override the (default) production address.
        """
        return os.environ.get(
            'BLENDER_ID_ENDPOINT', "https://www.blender.org/id")


def validate(token):
    import requests
    payload = dict(
        token=token)
    try:
        r = requests.post("{0}/u/validate_token".format(
            SystemUtility.blender_id_endpoint()), data=payload)
    except requests.exceptions.ConnectionError as e:
        raise e

    if r.status_code == 200:
        message = r.json()['message']
        valid = r.json()['valid']
    else:
        message = ""
        valid = False
    return dict(valid=valid, message=message)


class TokensAuth(TokenAuth):
    def check_auth(self, token, allowed_roles, resource, method):
        # print (token)
        validation = validate(token)
        # print validation['message']
        return validation['valid']
        """tokens = app.data.driver.db['tokens']
        lookup = {'token': token}
        token = tokens.find_one(lookup)
        if not token:
            return False
        users = app.data.driver.db['users']
        lookup = {'firstname': token['username']}
        if allowed_roles:
            lookup['role'] = {'$in': allowed_roles}
        user = users.find_one(lookup)
        if not user:
            return False
        return token"""

class BasicsAuth(BasicAuth):
    def check_auth(self, username, password, allowed_roles, resource, method):
        return username == 'admin' and password == 'secret'


class MyTokenAuth(BasicsAuth):
    """Switch between Basic and Token auth"""
    def __init__(self):
        self.token_auth = TokensAuth()
        self.authorized_protected = BasicsAuth.authorized

    def authorized(self, allowed_roles, resource, method):
        if resource=='tokens':
            return self.authorized_protected(self, allowed_roles, resource, method)
        else:
            return self.token_auth.authorized(allowed_roles, resource, method)

    def authorized_protected(self):
        pass


class ValidateCustomFields(Validator):
    def _validate_valid_properties(self, valid_properties, field, value):
        node_types = app.data.driver.db['node_types']
        lookup = {}
        lookup['_id'] = ObjectId(self.document['node_type'])
        node_type = node_types.find_one(lookup)

        v = Validator(node_type['dyn_schema'])
        val = v.validate(value)
        if val:
            return True
        else:
            print (val.errors)
            self._error(
                field, "Error validating properties")


"""def add_token(documents):
    for document in documents:
        document["token"] = (''.join(random.choice(string.ascii_uppercase)
                                     for x in range(10)))"""


app = Eve(validator=ValidateCustomFields, auth=MyTokenAuth)
# app.on_insert_tokens += add_token
