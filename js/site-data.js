/* Publication-bound reads. Never combine bytes from different generations. */
(function (root) {
    const cache = new Map();
    let summaryTimestamp = '';
    let cachedResponse = false;
    const updateConnectionStatus = () => {
        const status = root.document?.getElementById('connection-status');
        if (!status) return;
        const offline = root.navigator?.onLine === false;
        status.hidden = !offline && !cachedResponse;
        status.textContent = status.hidden ? '' : `${offline ? 'Offline' : 'Cached data'} — showing cached snapshot data.${summaryTimestamp ? ' Latest snapshot: ' + summaryTimestamp + '.' : ''}`;
    };
    root.addEventListener?.('online', updateConnectionStatus);
    root.addEventListener?.('offline', updateConnectionStatus);
    root.document?.addEventListener('DOMContentLoaded', updateConnectionStatus);
    const mismatch = () => new Error('Published data changed or is inconsistent. Refresh the page to load one complete generation.');
    const memo = (key, read) => {
        if (!cache.has(key)) cache.set(key, Promise.resolve().then(read).catch(error => { cache.delete(key); throw error; }));
        return cache.get(key);
    };
    const digest = async bytes => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
    const json = async (path, manifest) => {
        const response = await fetch(path, {cache: 'no-cache'});
        if (!response.ok) throw new Error('Could not load ' + path + ' (HTTP ' + response.status + '). Retry when connected.');
        if (path === 'data/site_summary.json') cachedResponse = response.headers.get('X-Site-Cache') === 'offline';
        const bytes = await response.arrayBuffer();
        if (manifest && (!manifest.artifacts[path] || await digest(bytes) !== manifest.artifacts[path])) throw mismatch();
        try { return JSON.parse(new TextDecoder().decode(bytes)); } catch (_) { throw new Error('Invalid data in ' + path + '. Retry or refresh the page.'); }
    };
    const manifest = () => memo('manifest', async () => {
        const data = await json('data/publication.json');
        if (data.schemaVersion !== 1 || !data.generationId || !data.scoringRevision || !data.artifacts ||
            Object.entries(data.artifacts).some(([path, hash]) => path.startsWith('/') || path.split('/').includes('..') || !/^[a-f0-9]{64}$/.test(hash))) throw mismatch();
        return data;
    });
    const loadSummary = () => memo('summary', async () => {
        const publication = await manifest();
        const data = await json('data/site_summary.json', publication);
        if (data.schemaVersion !== 1 || data.generationId !== publication.generationId || data.scoringRevision !== publication.scoringRevision ||
            !data.catalogFingerprint || !data.current || data.current.scoring?.revision !== data.scoringRevision || !Array.isArray(data.history) || !Array.isArray(data.benchmarks) || data.benchmarks.length !== 18 || data.benchmarks.some(b => !b.id || !b.column || !Number.isFinite(b.weight))) throw mismatch();
        const rows = ['US','CN'].flatMap(country => {
            if (!Array.isArray(data.current.teams?.[country])) throw mismatch();
            return data.current.teams[country];
        });
        if (!rows.length || rows.some(row => !row.modelId || !row.profileId || ['avgIq','value','unified'].some(key => !Number.isFinite(row[key])))) throw new Error('Leaderboard data is empty or invalid. Refresh or retry.');
        if (!Number.isFinite(Date.parse(data.current.timestamp)) || !data.history.length || data.history.some(s => !Number.isFinite(Date.parse(s.timestamp)) || s.scoringRevision !== data.scoringRevision || ['US','CN'].some(c => !s.scores?.[c] || ['total','count','avgIq','avgValue'].some(k => !Number.isFinite(s.scores[c][k]))))) throw mismatch();
        summaryTimestamp = data.current.timestamp;
        updateConnectionStatus();
        return data;
    });
    const loadCatalog = () => memo('catalog', async () => {
        const summary = await loadSummary();
        const data = await json('data/model_catalog.json', await manifest());
        if (!data.models || !Array.isArray(data.components) || !data.components.length || data.components.some(c => !c.id || !c.column) || Object.values(data.models).some(m => !m.profiles || !m.benchmarks)) throw mismatch();
        for (const rows of Object.values(summary.current.teams)) for (const row of rows) if (!data.models[row.modelId]?.profiles?.[row.profileId]) throw mismatch();
        return data;
    });
    const loadSnapshot = timestamp => memo('snapshot:' + timestamp, async () => {
        const summary = await loadSummary();
        if (!summary.history.some(s => s.timestamp === timestamp)) throw new Error('Snapshot is not available. Choose a retained date.');
        const path = timestamp === summary.current.timestamp ? 'current.json' : 'models.json';
        const data = await memo(path, async () => json(path, await manifest()));
        const snapshot = data.history?.find(s => s.timestamp === timestamp);
        if (!snapshot || (snapshot.scoring?.revision || snapshot.scoringRevision) !== summary.scoringRevision || data.scoringRevision !== summary.scoringRevision) throw mismatch();
        return root.ModelStore.hydrate({...data, history:[snapshot]}, await loadCatalog()).history[0];
    });
    root.SiteData = {loadSummary, loadCatalog, loadSnapshot, reset: () => cache.clear()};
})(typeof window !== 'undefined' ? window : globalThis);
