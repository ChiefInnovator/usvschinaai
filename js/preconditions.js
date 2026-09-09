/* Input contracts shared by page actions and the model catalog reader. */
(function (root) {
    function check(method, args, rules) {
        if (typeof method !== 'string' || !method || !args || !Array.isArray(rules)) {
            throw new TypeError('Invalid precondition declaration');
        }
        // Browser event handlers receive an Event even when they need no inputs.
        if (!rules.length && args.length === 1 && typeof Event !== 'undefined' && args[0] instanceof Event) return;
        if (args.length > rules.length) throw new TypeError(method + ': unexpected arguments');
        rules.forEach((rule, i) => {
            const value = args[i];
            if (rule.startsWith('?') && value == null) return;
            const kind = rule.replace(/^\?/, '');
            const valid = kind === 'mapping' ? value !== null && typeof value === 'object' && !Array.isArray(value) :
                kind === 'text' ? typeof value === 'string' :
                kind === 'index' ? Number.isInteger(value) && value >= 0 :
                kind === 'json' ? value === null || ['string', 'number', 'boolean', 'object'].includes(typeof value) :
                kind.startsWith('enum:') ? kind.slice(5).split('|').includes(value) : false;
            if (!valid) throw new TypeError(method + ': argument ' + (i + 1) + ' must satisfy ' + rule);
        });
    }
    function rosterIndex(index, length) {
        if (!Number.isInteger(index) || !Number.isInteger(length) || index < 0 || index >= length) {
            throw new RangeError('Archive index must reference an existing snapshot');
        }
    }
    root.AppContract = {check, rosterIndex};
    if (typeof module !== 'undefined') module.exports = root.AppContract;
})(typeof window !== 'undefined' ? window : globalThis);
