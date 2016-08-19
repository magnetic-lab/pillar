import logging

from bson import ObjectId
from datetime import datetime
from eve.io.mongo import Validator
from flask import current_app

log = logging.getLogger(__name__)


class ValidateCustomFields(Validator):
    def convert_properties(self, properties, node_schema):
        date_format = current_app.config['RFC1123_DATE_FORMAT']

        for prop in node_schema:
            if not prop in properties:
                continue
            schema_prop = node_schema[prop]
            prop_type = schema_prop['type']
            if prop_type == 'dict':
                properties[prop] = self.convert_properties(
                    properties[prop], schema_prop['schema'])
            if prop_type == 'list':
                if properties[prop] in ['', '[]']:
                    properties[prop] = []
                for k, val in enumerate(properties[prop]):
                    if not 'schema' in schema_prop:
                        continue
                    item_schema = {'item': schema_prop['schema']}
                    item_prop = {'item': properties[prop][k]}
                    properties[prop][k] = self.convert_properties(
                        item_prop, item_schema)['item']
            # Convert datetime string to RFC1123 datetime
            elif prop_type == 'datetime':
                prop_val = properties[prop]
                properties[prop] = datetime.strptime(prop_val, date_format)
            elif prop_type == 'objectid':
                prop_val = properties[prop]
                if prop_val:
                    properties[prop] = ObjectId(prop_val)
                else:
                    properties[prop] = None

        return properties

    def _validate_valid_properties(self, valid_properties, field, value):
        from pillar.api.utils import project_get_node_type

        projects_collection = current_app.data.driver.db['projects']
        lookup = {'_id': ObjectId(self.document['project'])}

        project = projects_collection.find_one(lookup, {
            'node_types.name': 1,
            'node_types.dyn_schema': 1,
        })
        if project is None:
            log.warning('Unknown project %s, declared by node %s',
                        lookup, self.document.get('_id'))
            self._error(field, 'Unknown project')
            return False

        node_type_name = self.document['node_type']
        node_type = project_get_node_type(project, node_type_name)
        if node_type is None:
            log.warning('Project %s has no node type %s, declared by node %s',
                        project, node_type_name, self.document.get('_id'))
            self._error(field, 'Unknown node type')
            return False

        try:
            value = self.convert_properties(value, node_type['dyn_schema'])
        except Exception as e:
            log.warning("Error converting form properties", exc_info=True)

        v = Validator(node_type['dyn_schema'])
        val = v.validate(value)

        if val:
            return True

        log.warning('Error validating properties for node %s: %s', self.document, v.errors)
        self._error(field, "Error validating properties")
