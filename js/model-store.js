/* Expand shared model records for the existing leaderboard/archive renderers. */
(function (root) {
    const AppContract = root.AppContract || (typeof require !== 'undefined' && require('./preconditions.js'));
    const catalogs = new Map();
    function hydrate(data, catalog) {
            AppContract.check("hydrate", arguments, ["mapping", "mapping"]);
        if (data.schemaVersion !== 2) return data;
        const result = {...data, history: data.history.map(snapshot => {
            const teams = {};
            for (const [country, rows] of Object.entries(snapshot.teams)) {
                teams[country] = rows.map(ref => {
                    const model = catalog.models[ref.modelId];
                    const profile = model && model.profiles[ref.profileId];
                    if (!profile) throw new Error('Missing shared model/profile: ' + ref.modelId);
                    const row = {...profile, ...ref, _provenance: {}};
                    for (const component of catalog.components) {
                        const key = component.column;
                        row[key] = '—';
                        const candidates = Object.entries(model.benchmarks[component.id] || {})
                            .filter(([, r]) => !r.excludedReason && r.availableFrom <= snapshot.timestamp.slice(0, 10))
                            .sort(([aid, a], [bid, b]) => b.score - a.score ||
                                a.availableFrom.localeCompare(b.availableFrom) || aid.localeCompare(bid));
                        if (candidates.length) {
                            const [id, r] = candidates[0];
                            row[key] = `${r.score}%`;
                            row._provenance[key] = {type: 'historical-evidence', url: r.source,
                                evidenceId: id, configuration: r.configuration,
                                availableFrom: r.availableFrom, retrievedAt: r.retrievedAt};
                        }
                    }
                    delete row.modelId;
                    delete row.profileId;
                    return row;
                });
            }
            return {...snapshot, teams};
        })};
        return result;
    }
    async function expand(data) {
            AppContract.check("expand", arguments, ["mapping"]);
        if (data.schemaVersion !== 2) return data;
        const url = data.modelCatalog;
        if (!catalogs.has(url)) {
            catalogs.set(url, fetch(url).then(response => {
                if (!response.ok) throw new Error('Shared model catalog HTTP ' + response.status);
                return response.json();
            }).catch(error => { catalogs.delete(url); throw error; }));
        }
        try {
            return hydrate(data, await catalogs.get(url));
        } catch (error) {
            catalogs.delete(url);
            throw error;
        }
    }
    root.ModelStore = {hydrate, expand};
    if (typeof module !== 'undefined') module.exports = root.ModelStore;
})(typeof window !== 'undefined' ? window : globalThis);
