import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from avg_iq_benchmarks import load_config, selected_weights
from scoring import score_cohort, score_avg_iq_cohort, calculate_derived_scores
from rescore_history import apply_evidence, replay, validate_evidence
from test_scoring import E


class WeightedInputsTests(unittest.TestCase):
    def test_hle_and_swe_verified_keep_benchmark_boundaries(self):
        from avg_iq_benchmarks import selected_value
        self.assertEqual(selected_value({'HLE': '40%'}, 'Humanity’s Last Exam'), '40%')
        self.assertEqual(selected_value({'HLE': '40%'}, 'Agents’ Last Exam'), '')
        self.assertEqual(selected_weights(['HLE (no tools, text only)', 'HLE with tools', 'SWE-bench Pro', 'SWE-bench Lite']), {})
        self.assertEqual(selected_value({'SWE-BenchVerified': '80%'}, 'SWE-bench Verified'), '80%')
        weights = selected_weights(['Humanity’s Last Exam', 'SWE-bench Verified', 'DeepSWE'])
        model = E('M', 'US', **{'HLE': '40%', 'SWE-benchVerified': '80%'})
        result = score_avg_iq_cohort([model], log=lambda *a: None)
        self.assertEqual(result.coverage(model), (2, 18))
        self.assertEqual(result.scores_for(model)['avgIq'],
                         round(40 * weights['Humanity’s Last Exam'] + 80 * weights['SWE-bench Verified'], 2))

    def entries(self):
        return [E(str(i), 'US', Toolathlon=f'{90-i}%', **{
            'DeepSWE1.1': f'{30+i}%', 'BrowseComp': f'{70-i}%', 'Other': f'{20+i}%'}) for i in range(8)]

    def test_configuration_and_exact_versions(self):
        b = load_config()['benchmarks']
        self.assertEqual(len(b), 18)
        self.assertAlmostEqual(sum(x['weight'] for x in b), 100)
        self.assertTrue(all(x['weight'] >= 0 for x in b))
        self.assertEqual(selected_weights(['GPQA Extended', 'DeepSWE 1.0', 'Terminal-Bench2.0', 'FrontierMath', 'ARC-AGI', 'CharXiv']), {})
        self.assertEqual(selected_weights(['DeepSWE1.1']), {'DeepSWE1.1': next(b['weight']/100 for b in load_config()['benchmarks'] if b['id']=='deepswe-1.1')})

    def test_deepswe_versions_have_independent_weights_and_scores(self):
        from avg_iq_benchmarks import selected_value
        weights=selected_weights(['DeepSWE','DeepSWE1.1'])
        self.assertEqual(selected_value({'DeepSWE1.1':'90%'},'DeepSWE'),'')
        self.assertEqual(selected_value({'DeepSWE':'80%'},'DeepSWE1.1'),'')
        model=E('M','US',**{'DeepSWE':'80%','DeepSWE1.1':'90%'})
        scored=score_avg_iq_cohort([model],log=lambda *a:None)
        self.assertEqual(scored.scores_for(model)['avgIq'],round(80*weights['DeepSWE']+90*weights['DeepSWE1.1'],2))
        self.assertEqual(scored.coverage(model),(2,18))

    def test_livecodebench_v6_allocation_and_version_boundary(self):
        from avg_iq_benchmarks import selected_value
        weights=selected_weights(['LiveCodeBench v6','DeepSWE','DeepSWE1.1'])
        self.assertEqual(selected_value({'LiveCodeBench':'99%','LiveCodeBench v5':'98%'},'LiveCodeBench v6'),'')
        model=E('M','CN',**{'LiveCodeBenchv6':'80%'})
        result=score_avg_iq_cohort([model],log=lambda *a:None)
        self.assertEqual(result.coverage(model),(1,18))
        self.assertEqual(result.scores_for(model)['avgIq'],round(80*weights['LiveCodeBench v6'],2))

    def test_new_benchmarks_and_gpqa_subsets_score_separately(self):
        from avg_iq_benchmarks import selected_value
        self.assertEqual(selected_value({'GPQA':'90%'},'GPQA Diamond'),'')
        self.assertEqual(selected_value({'GPQA Diamond':'90%'},'GPQA'),'')
        model=E('M','US',**{'GPQA':'80%','GPQADiamond':'90%','MMLU-Pro':'70%','AIME2025':'60%'})
        result=score_avg_iq_cohort([model],log=lambda *a:None)
        self.assertEqual(result.coverage(model),(3,18))
        weights=selected_weights(['GPQA','GPQA Diamond','MMLU-Pro','AIME 2025'])
        self.assertNotIn('AIME 2025', weights)
        expected=80*weights['GPQA']+90*weights['GPQA Diamond']+70*weights['MMLU-Pro']
        self.assertEqual(result.scores_for(model)['avgIq'],round(expected,2))

    def test_fixed_denominator_drives_value_and_formula(self):
        entries = self.entries()
        headers = ['Toolathlon', 'DeepSWE1.1', 'BrowseComp', 'Other']
        new = score_avg_iq_cohort(entries, headers, log=lambda *a: None)
        self.assertEqual(new.scores_for(entries[0])['avgIq'], round(90*selected_weights(['Toolathlon'])['Toolathlon']+30*selected_weights(['DeepSWE1.1'])['DeepSWE1.1']+70*selected_weights(['BrowseComp'])['BrowseComp'], 2))
        for e in entries:
            from scoring import parse_to_number
            cost = parse_to_number(e.columns['Input$/M']) + parse_to_number(e.columns['Output$/M'])
            raw = new.scores_for(e, round_results=False)
            self.assertAlmostEqual(raw['value'], raw['avgIq']/cost)
            s = new.scores_for(e, round_results=False)
            def norm(v, lo, hi):
                return max(0, min(100, (v-lo)/(hi-lo)*100)) if hi>lo else v
            expected = 10*(.9*norm(s['avgIq'], new.min_avg_iq,new.max_avg_iq)+.1*norm(s['value'],new.min_value,new.max_value))
            self.assertAlmostEqual(s['unified'], expected)

    def test_single_report_counts_and_missing_is_zero(self):
        entries = self.entries()
        entries[0].columns['DeepSWE1.1'] = '—'
        entries[0].columns['IFBench'] = '95%'
        before = copy.deepcopy([e.columns for e in entries])
        result = score_avg_iq_cohort(entries, ['Toolathlon','DeepSWE1.1','BrowseComp','IFBench'], log=lambda *a: None)
        self.assertEqual(result.scores_for(entries[0])['avgIq'], round(90*selected_weights(['Toolathlon'])['Toolathlon']+70*selected_weights(['BrowseComp'])['BrowseComp']+95*selected_weights(['IFBench'])['IFBench'],2))
        self.assertIn('IFBench', result.benchmark_headers)
        self.assertEqual(len(result.qualified_benchmarks),18)
        self.assertEqual(result.qualified_min_reports,0)
        self.assertEqual([e.columns for e in entries], before)

    def test_astra_browsecomp_counts_even_as_only_reporter(self):
        entries=[E('Astra','US',BrowseComp='91.5%')]+[E(str(i),'CN') for i in range(19)]
        result=score_avg_iq_cohort(entries,['BrowseComp'],log=lambda *a: None)
        self.assertEqual(result.scores_for(entries[0])['avgIq'],round(91.5*selected_weights(['BrowseComp'])['BrowseComp'],2))
        self.assertEqual(result.scores_for(entries[1])['avgIq'],0)
        self.assertEqual(len(result.benchmark_headers),18)

    def test_muse_example_keeps_all_twelve_allocations_in_denominator(self):
        e=E('Muse Spark 1.3','US', **{'DeepSWE1.1':'75.4%', 'Terminal-Bench2.1':'88.8%'})
        result=calculate_derived_scores(e, ['DeepSWE1.1','Terminal-Bench2.1'],
            qualified_benchmarks={'DeepSWE1.1','Terminal-Bench2.1'},
            benchmark_weights={'DeepSWE1.1':.15,'Terminal-Bench2.1':.1})
        self.assertEqual(result['avgIq'],20.19)

    def test_configured_weights_ignore_participation(self):
        e = E('a','US', Toolathlon='80%', **{'DeepSWE1.1':'40%'})
        s = calculate_derived_scores(e, ['Toolathlon','DeepSWE1.1'], {'Toolathlon':4,'DeepSWE1.1':8},8,
              benchmark_weights={'Toolathlon':.1,'DeepSWE1.1':.15})
        self.assertEqual(s['avgIq'], 14)

    def test_aliases_are_one_component_and_never_maximized(self):
        entries = self.entries()
        for e in entries:
            e.columns['ARC-AGIv2'] = '50%'
            e.columns['ARC-AGI-2'] = '10%'
        result = score_avg_iq_cohort(entries, ['Toolathlon','DeepSWE1.1','BrowseComp','ARC-AGIv2','ARC-AGI-2'],log=lambda *a: None)
        self.assertEqual(len([k for k in result.benchmark_headers if k.startswith('ARC')]),1)
        self.assertEqual(result.scores_for(entries[0])['avgIq'], round(90*selected_weights(['Toolathlon'])['Toolathlon']+30*selected_weights(['DeepSWE1.1'])['DeepSWE1.1']+70*selected_weights(['BrowseComp'])['BrowseComp']+10*selected_weights(['ARC-AGI-2'])['ARC-AGI-2'],2))

    def test_serialized_inputs_reproduce_all_scores(self):
        entries=self.entries()
        result=score_avg_iq_cohort(entries,list(entries[0].columns)[2:],log=lambda *a: None)
        fixed=score_cohort(entries,result.benchmark_headers,drop_sparse=False,fixed=result.to_snapshot())
        self.assertEqual([result.scores_for(e) for e in entries],[fixed.scores_for(e) for e in entries])


class HistoricalEvidenceTests(unittest.TestCase):
    def evidence(self):
        return {'results':[{'id':'example','model':'Exact model','component':'gpqa-diamond','score':80,'unit':'percent',
             'source':'https://example.com/report','configuration':'no tools','availableFrom':'2026-03-05',
             'publishedAt':'2026-03-05','retrievedAt':'2026-09-06'}]}

    def snapshot(self, day):
        return {'timestamp':day+'T12:00:00+00:00','teams':{'US':[{'model':'Exact model','GPQA Extended':'90%','Input$/M':'$1','Output$/M':'$1'}],'CN':[{'model':'Exact model Pro'}]}}

    def test_no_backdating_successor_substitution_or_generic_overwrite(self):
        evidence=self.evidence();validate_evidence(evidence)
        old=self.snapshot('2026-03-04');self.assertEqual(apply_evidence(old,evidence),[])
        today=self.snapshot('2026-03-05');self.assertEqual(len(apply_evidence(today,evidence)),1)
        self.assertEqual(today['teams']['US'][0]['GPQA Extended'],'90%')
        self.assertEqual(today['teams']['US'][0]['GPQADiamond'],'80%')
        self.assertNotIn('GPQADiamond',today['teams']['CN'][0])
        self.assertEqual(apply_evidence(today,evidence),[])

    def test_old_value_inputs_and_benchmarks_are_removed_on_replay(self):
        snapshot=self.snapshot('2026-03-05')
        snapshot['teams']['US']=[{'model':str(i), 'MRCRv2':'90%', 'MRCRv2(8-needle)':'80%',
            'Other':'50%', 'Input$/M':'$1', 'Output$/M':'$1'} for i in range(8)]
        snapshot['teams']['CN']=[]
        data={'history':[snapshot]}
        replay(data,{'results':[]});once=copy.deepcopy(data)
        replay(data,{'results':[]})
        self.assertEqual(data,once)
        self.assertNotIn('valueInputs', snapshot['scoring'])
        for row in snapshot['teams']['US']:
            self.assertNotIn('MRCRv2', row)
            self.assertNotIn('Other', row)
            self.assertEqual(row['avgIq'], 0)
            self.assertEqual(row['value'], 0)

    def test_rebuild_discards_all_old_scores_and_uses_only_dated_evidence(self):
        data={'history':[self.snapshot('2026-03-05'),self.snapshot('2026-03-04')]}
        for snap in data['history']:
            snap['teams']['US'][0].update({'Toolathlon':'99%', 'avgIq':99, 'value':99})
            snap['scoring']={'valueInputs':{'obsolete':True}}
        replay(data,self.evidence(),rebuild=True)
        today=data['history'][0]['teams']['US'][0]
        earlier=data['history'][1]['teams']['US'][0]
        self.assertEqual(today['avgIq'],round(80*selected_weights(['GPQA Diamond'])['GPQA Diamond'],2))
        self.assertEqual(today['value'],round(40*selected_weights(['GPQA Diamond'])['GPQA Diamond'],2))
        self.assertEqual(earlier['avgIq'],0.0)
        self.assertEqual(today['GPQA'],'—')
        self.assertNotIn('GPQA Extended',today)
        self.assertEqual(today['Toolathlon'],'—')
        self.assertNotIn('valueInputs',data['history'][0]['scoring'])

    def test_excluded_configuration_does_not_fill(self):
        evidence=self.evidence()
        evidence['results'][0]['excludedReason']='Mixed model fallback'
        snap=self.snapshot('2026-03-05')
        self.assertEqual(apply_evidence(snap,evidence),[])
        self.assertNotIn('GPQADiamond',snap['teams']['US'][0])

    def test_reject_inconsistent_dates(self):
        evidence=self.evidence();evidence['results'][0]['availableFrom']='2026-03-04'
        with self.assertRaises(ValueError): validate_evidence(evidence)

    def test_replay_preserves_membership_is_idempotent_and_removes_prior_scores(self):
        data={'history':[self.snapshot('2026-03-05'),self.snapshot('2026-03-04')]}
        data['history'][0]['teams']['US'][0]['_prior']={'avgIq':99}
        evidence=self.evidence();report=replay(data,evidence)
        self.assertEqual(report['snapshots'],2)
        once=copy.deepcopy(data);replay(data,evidence)
        self.assertEqual(data,once)
        self.assertNotIn('_prior',data['history'][0]['teams']['US'][0])
        self.assertEqual([r['model'] for r in data['history'][0]['teams']['US']],['Exact model'])


if __name__ == '__main__': unittest.main()
