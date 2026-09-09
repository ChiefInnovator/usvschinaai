#!/usr/bin/env python3
"""Refresh selected benchmark evidence for retained llm-stats models without an API key.

python scripts/refresh_benchmark_sources.py --write
The daily scraper calls refresh_sources before paid web research. Source failures
are isolated, audited and never treated as zero-valued benchmark results.
"""
from preconditions import preconditions
import argparse
import concurrent.futures
import csv
import io
from model_store import load_data, load_evidence, save_evidence
import json
import re
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

from avg_iq_benchmarks import load_config, selected_value
from harvest_benchmark_sources import (fetch, harvest_aa, harvest_epoch,
    observed_values, FINGERPRINT_COLUMNS, EPOCH_ZIP, EPOCH_TABLES, AA_PAGE, strip_effort)
from ingest_benchmark_findings import normalize, model_first_seen, resolve_model
from benchmark_leaderboard_sources import VALS_SOURCES, vals_results, ale_results

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'data/model_catalog.json'
AUDIT = ROOT / 'data/benchmark_source_refresh.json'


@preconditions(model='text', component='nonempty', score='number', source='text', configuration='text', published='?date')
def finding(model, component, score, source, configuration, published=None):
    return dict(model=model, component=component, score=score, sourceUrl=source,
                sourceType='official_leaderboard', confidence='high',
                configuration=configuration, publishedAt=published)


class Tables(HTMLParser):
    """Read plain text table cells; never guess image/chart values."""
    @preconditions()
    def __init__(self):
        super().__init__(); self.tables=[]; self.table=None; self.row=None; self.cell=None
    @preconditions(tag='text', attrs='sequence')
    def handle_starttag(self, tag, attrs):
        if tag == 'table': self.table=[]
        elif tag == 'tr' and self.table is not None: self.row=[]
        elif tag in ('td','th') and self.row is not None: self.cell=''
    @preconditions(data='text')
    def handle_data(self, data):
        if self.cell is not None: self.cell += data
    @preconditions(tag='text')
    def handle_endtag(self, tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(self.cell); self.cell=None
        elif tag == 'tr' and self.row is not None:
            self.table.append(self.row); self.row=None
        elif tag == 'table' and self.table is not None:
            self.tables.append(self.table); self.table=None


@preconditions(html='text', models='mapping')
def original_toolathlon(html, models):
    # Fail closed if the operator changes the original-series boundary.
    marker='Previous Toolathlon leaderboard'
    if marker not in html: raise ValueError('Original Toolathlon series boundary missing')
    parser=Tables(); parser.feed(html.split(marker,1)[1])
    if not parser.tables: raise ValueError('Original Toolathlon table missing')
    results=[]
    for row in parser.tables[0][1:]:
        if len(row)<5: continue
        label=re.sub('[✓†‡]', '', row[0]).strip()
        name=re.sub(r'-(?:xhigh|high|medium|low)$', '', label)
        model=resolve_model(name, models)
        score=re.match(r'\s*([0-9.]+)',row[4])
        if model and score and re.fullmatch(r'\d{4}-\d{2}-\d{2}',row[3]):
            results.append(finding(model,'toolathlon',float(score[1]),
                'https://toolathlon.xyz/docs/leaderboard',
                f'Original pre-Verified Toolathlon; {label}; {row[2]} harness; Pass@1.',row[3]))
    return results


@preconditions(text='text', models='mapping')
def charxiv_results(text, models):
    results=[]
    rows=list(csv.reader(io.StringIO(text)))
    if not rows or rows[0][3]!='Overall': raise ValueError('CharXiv reasoning column changed')
    for row in rows[1:]:
        model=resolve_model(strip_effort(row[0]),models)
        if model:
            results.append(finding(model,'charxiv-r',float(row[3]),
                'https://charxiv.github.io/data/val_result.csv',
                f'CharXiv validation reasoning Overall, zero-shot; {row[0]}.'))
    return results


@preconditions(model='text', url='text')
def detail_results(model, url):
    # Lazy import avoids a circular import when invoked by the scraper.
    from scrape_models import extract_detail_benchmarks
    html=fetch(url)
    scores=extract_detail_benchmarks(SimpleNamespace(content=lambda:html))
    return [dict(finding(model,b['id'],float(value.rstrip('%')),url,
                  'Exact model detail-page benchmark identity and normalized percentage.'),
                 sourceType='third_party_leaderboard',confidence='medium')
            for b in load_config()['benchmarks']
            if (value:=selected_value(scores,b['name']))]


@preconditions(evidence='mapping', findings='sequence', models='mapping', retrieved='date')
def accept_findings(evidence, findings, models, retrieved):
    """Retain distinct verified observations for highest-score, date-safe replay."""
    components={b['id']:b for b in load_config()['benchmarks']}
    ids={r['id'] for r in evidence['results']}
    accepted=[]; rejected=[]
    for item in findings:
        config=(item.get('configuration','')+' '+item.get('notes','')).lower()
        if 'fallback' in config or 'toolathlon-verified' in config:
            rejected.append({'model':item.get('model'),'component':item.get('component'),
                             'reason':'Mixed model or distinct benchmark configuration requires review'})
            continue
        record,reason=normalize(item,components,evidence.get('benchmarkAvailability',{}),models,
                                retrieved_at=retrieved)
        if reason:
            rejected.append({'model':item.get('model'),'component':item.get('component'),'reason':reason})
            continue
        pair=(record['model'],record['component'])
        if record['id'] in ids: continue
        evidence['results'].append(record);accepted.append(record)
        ids.add(record['id'])
    return accepted,rejected


@preconditions(entries='sequence')
def persist_ai_findings(entries):
    """Retain accepted research for dated historical replay, including configuration."""
    retrieved=datetime.now(timezone.utc).date().isoformat()
    models=model_first_seen()
    findings=[]
    for entry in entries:
        models.setdefault(entry.name,retrieved)
        for component in load_config()['benchmarks']:
            value=selected_value(entry.columns,component['name'])
            provenance=entry.columns.get('_provenance',{}).get(component['name'],{})
            if not value or provenance.get('source')!='ai_filled': continue
            findings.append(dict(model=entry.name,component=component['id'],score=value,
                sourceUrl=provenance.get('url'),sourceType=provenance.get('source_type'),
                confidence=provenance.get('confidence'),
                configuration=provenance.get('notes') or 'Configuration not stated in research.'))
    evidence=load_evidence(EVIDENCE)
    accepted,rejected=accept_findings(evidence,findings,models,retrieved)
    if accepted: save_evidence(evidence, EVIDENCE)
    return accepted,rejected


@preconditions(entries='sequence', write='bool')
def refresh_sources(entries=(), *, write=False):
    retrieved=datetime.now(timezone.utc).date().isoformat()
    data=load_data(ROOT / 'models.json')
    urls={r['model']:r['link'] for s in reversed(data['history'])
          for rows in s['teams'].values() for r in rows}
    models=model_first_seen(); observed=observed_values()
    for entry in entries:
        urls[entry.name]=entry.url;models.setdefault(entry.name,retrieved)
        current=observed.setdefault(entry.name,{})
        for component in load_config()['benchmarks']:
            value=selected_value(entry.columns,component['name'])
            if value and component['name'] in FINGERPRINT_COLUMNS:
                current[FINGERPRINT_COLUMNS[component['name']]]=float(str(value).rstrip('%'))
    sources={
        'artificial-analysis':lambda:fetch(AA_PAGE),
        'epoch':lambda:fetch(EPOCH_ZIP,binary=True),
        'toolathlon':lambda:original_toolathlon(fetch('https://toolathlon.xyz/docs/leaderboard'),models),
        'charxiv':lambda:charxiv_results(fetch('https://charxiv.github.io/data/val_result.csv'),models),
        'agents-last-exam':lambda:ale_results(json.loads(fetch(
            'https://agents-last-exam.org/api/demo/leaderboard')),models),
    }
    sources.update({f'llm-stats:{name}':lambda n=name,u=url:detail_results(n,u) for name,url in urls.items()})
    configured = {b['id'] for b in load_config()['benchmarks']}
    sources.update({f'vals:{slug}':lambda s=slug:vals_results(
        fetch('https://www.vals.ai/benchmarks/'+s),s,models)
        for slug, spec in VALS_SOURCES.items() if spec[0] in configured})
    payloads={}; failures=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        jobs={pool.submit(fn):name for name,fn in sources.items()}
        for job in concurrent.futures.as_completed(jobs):
            name=jobs[job]
            try: payloads[name]=job.result()
            except Exception as exc: failures.append({'source':name,'error':str(exc)})
    findings=[]; skipped=[]; efforts={}; coverage=[]
    if 'artificial-analysis' in payloads:
        try:
            found,ambiguous,efforts=harvest_aa(payloads['artificial-analysis'],list(models),observed)
            findings.extend(found);skipped.extend(ambiguous)
        except Exception as exc: failures.append({'source':'artificial-analysis','error':str(exc)})
    if 'epoch' in payloads:
        try:
            with zipfile.ZipFile(io.BytesIO(payloads['epoch'])) as archive:
                tables={Path(n).name:list(csv.DictReader(io.StringIO(archive.read(n).decode('utf8'))))
                        for n in archive.namelist() if Path(n).name in EPOCH_TABLES}
            found,ambiguous=harvest_epoch(tables,list(models),observed,efforts)
            for record in found:
                # An evaluation start is not a public release date.
                record['publishedAt']=None
            findings.extend(found);skipped.extend(ambiguous)
        except Exception as exc: failures.append({'source':'epoch','error':str(exc)})
    for name in sources:
        if name not in ('epoch','artificial-analysis'):
            if name.startswith('vals:') and name in payloads:
                records,audit=payloads[name]; findings.extend(records); coverage.append(audit)
            elif not name.startswith('vals:'):
                findings.extend(payloads.get(name,[]))
    evidence=load_evidence(EVIDENCE)
    accepted,rejected=accept_findings(evidence,findings,models,retrieved)
    report=dict(retrievedAt=retrieved,modelsChecked=len(models),sourcesChecked=len(sources),
                findings=len(findings),accepted=len(accepted),failures=failures,
                skippedConfigurations=skipped,rejected=rejected,leaderboardCoverage=coverage)
    if entries:
        from rescore_history import fill_current_entries
        fill_current_entries(entries, retrieved, evidence=evidence)
    if write:
        save_evidence(evidence, EVIDENCE)
        AUDIT.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print('[source-refresh] '+json.dumps({k:v for k,v in report.items() if not isinstance(v,list)}))
    for failure in failures: print('[source-refresh] unavailable: '+failure['source'])
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write',action='store_true')
    refresh_sources(write=parser.parse_args().write)
