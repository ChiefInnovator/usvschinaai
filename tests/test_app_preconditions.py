"""Positive/negative caller-contract tests for every application function/method.

Valid contracts are checked without executing network/publishing entry points.
Invalid calls invoke the real guarded method and must fail before its body.
Behavior after valid calls is covered by the unit and integration suites.
"""
import ast
from datetime import datetime,timezone
import importlib
import inspect
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from preconditions import PreconditionError

SAMPLES={
 'mapping':{'sample':'value'},'sequence':['sample'],'set':{'sample'},'iterable':{'sample':'value'}.keys(),
 'text':'sample','nonempty':'sample','path':Path('/tmp/test-only-contract.json'),
 'positive_int':1,'nonnegative_int':0,'enum:high|medium|low':'high',
 'bool':True,'int':1,'number':1.5,'positive':1,'nonnegative':0,
 'datetime':datetime(2026,9,7,tzinfo=timezone.utc),'date':'2026-09-07','timestamp':'2026-09-07T12:00:00Z',
 'callable':lambda value:value,'entry':SimpleNamespace(name='Model',columns={}),
 'candidate':SimpleNamespace(model_name='Model',benchmark='GPQA Diamond'),
 'response':SimpleNamespace(status_code=200,json=lambda:{}),
 'page':SimpleNamespace(locator=lambda selector:None),'namespace':SimpleNamespace(flag=True),
 'content_page':SimpleNamespace(content=lambda:''),
 'json':{'missing':None,'scores':[0,80.5]},
}
BAD={
 'mapping':[],'sequence':{},'set':[],'iterable':'wrong','text':17,'nonempty':' ',
 'positive_int':0,'nonnegative_int':-1,'enum:high|medium|low':'invalid',
 'path':'','bool':1,'int':True,'number':float('nan'),'positive':0,'nonnegative':-1,
 'datetime':'2026-09-07','date':'2026-02-30','timestamp':'not-a-timestamp',
 'callable':42,'entry':SimpleNamespace(columns=None),'candidate':{},'response':{},'page':{},'namespace':{},
 'json':object(),
 'content_page':SimpleNamespace(content='not callable'),
}


def application_methods():
    for path in sorted((Path(__file__).resolve().parents[1]/'scripts').glob('*.py')):
        if path.stem in ('preconditions','fit_benchmark_weights'):continue
        with patch('dotenv.load_dotenv'):
            module=importlib.import_module(path.stem)
        tree=ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                yield path.stem,node.name,getattr(module,node.name)
            elif isinstance(node,ast.ClassDef):
                cls=getattr(module,node.name)
                for method in node.body:
                    if isinstance(method,ast.FunctionDef) and (not method.name.startswith('__') or method.name=='__init__'):
                        yield path.stem,node.name+'.'+method.name,getattr(cls,method.name)


class ApplicationPreconditionTests(unittest.TestCase):
    pass


def make_positive(function):
    def test(self):
        self.assertTrue(hasattr(function,'check_preconditions'),'Missing declared caller contract')
        signature=inspect.signature(function);args={}
        for name,param in signature.parameters.items():
            rule=function.precondition_rules.get(name)
            if rule:args[name]=SAMPLES[rule.lstrip('?')]
            elif name in ('self','cls'):args[name]=object()
            elif param.default is inspect.Parameter.empty:args[name]=object()
        function.check_preconditions(**args)
        # Optional absence and default arguments must remain valid.
        for name,rule in function.precondition_rules.items():
            if rule.startswith('?'):function.check_preconditions(**{**args,name:None})
    return test


def make_negative(function):
    def test(self):
        self.assertTrue(hasattr(function,'check_preconditions'),'Missing declared caller contract')
        signature=inspect.signature(function);args={}
        for name,param in signature.parameters.items():
            rule=function.precondition_rules.get(name)
            if rule:args[name]=SAMPLES[rule.lstrip('?')]
            elif name in ('self','cls'):args[name]=object()
            elif param.default is inspect.Parameter.empty:args[name]=object()
        for name,rule in function.precondition_rules.items():
            with self.subTest(parameter=name):
                with self.assertRaises(PreconditionError):function(**{**args,name:BAD[rule.lstrip('?')]})
        # Also covers no-argument entry points without launching them.
        with self.assertRaises(TypeError):function(**{**args,'unexpected_caller_input':True})
    return test


for module,name,function in application_methods():
    label=module+'_'+name.replace('.','_')
    setattr(ApplicationPreconditionTests,'test_positive_'+label,make_positive(function))
    setattr(ApplicationPreconditionTests,'test_negative_'+label,make_negative(function))


class ContractMechanismTests(unittest.TestCase):
    def test_valid_calls_execute_and_invalid_calls_never_reach_body(self):
        from preconditions import preconditions
        calls=[]
        @preconditions(count='positive_int', enabled='bool')
        def action(count=1, *, enabled=True):
            calls.append(count);return enabled
        self.assertTrue(action());self.assertFalse(action(2,enabled=False))
        self.assertEqual(calls,[1,2])
        for args,kwargs in [((0,),{}),((1,),{'enabled':'yes'}),((1,2),{}),((1,),{'count':2}), ((),{'unexpected':3})]:
            with self.subTest(args=args,kwargs=kwargs),self.assertRaises((PreconditionError,TypeError)):action(*args,**kwargs)
        self.assertEqual(calls,[1,2])

    def test_guard_rejects_invalid_declaration_and_preserves_optional_defaults(self):
        from preconditions import preconditions, _accepts
        @preconditions(value='?text')
        def parser(value=None):return value
        self.assertIsNone(parser());self.assertEqual(parser(''), '')
        with self.assertRaises(PreconditionError):parser(42)
        with self.assertRaises(TypeError):preconditions(unknown='text')(lambda value:value)
        with self.assertRaises(PreconditionError):_accepts(None,'x')
        with self.assertRaises(ValueError):_accepts('unknown-rule','x')
