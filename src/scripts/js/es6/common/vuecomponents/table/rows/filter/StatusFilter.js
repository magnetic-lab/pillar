import {EnumFilter} from './EnumFilter'

const TEMPLATE =`
<enum-filter
    label="Status"
    :availableValues="availableEnumValues"
    :componentState="componentState"
    :rowObjects="rowObjects"
    :valueExtractorCB="extractStatus"
    @visibleRowObjectsChanged="$emit('visibleRowObjectsChanged', ...arguments)"
    @componentStateChanged="$emit('componentStateChanged', ...arguments)"
>
`;
/**
 * Filter row objects based on there status. 
 * 
 * @emits visibleRowObjectsChanged(rowObjects) When the objects to be visible has changed.
 * @emits componentStateChanged(newState) When row filter state changed.
 */
let StatusFilter = {
    template: TEMPLATE,
    props: {
        availableStatuses: Array, // Array with valid values ['abc', 'xyz']
        componentState: Object, // Instance of object that componentStateChanged emitted. To restore previous state.
        rowObjects: Array,
    },
    computed: {
        availableEnumValues() {
            let statusCopy = this.availableStatuses.concat().sort()
            return statusCopy.map(status =>{
                return {
                    value: status,
                    displayName: status.replace(/-|_/g, ' ') // Replace -(dash) and _(underscore) with space
                }
            });
        }
    },
    methods: {
        extractStatus(rowObject) {
            return rowObject.getStatus();
        },
    },
    components: {
        'enum-filter': EnumFilter,
    },
};

export { StatusFilter }
